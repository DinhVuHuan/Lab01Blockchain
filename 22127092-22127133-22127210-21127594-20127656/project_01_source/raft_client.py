import os
import sys
import grpc
import raft_pb2
import raft_pb2_grpc
import config
import time


def find_leader():
    """First try HTTP /state endpoint of each node (started by each RaftNode).
    If not available, fall back to sending AppendEntries (heuristic).
    """
    import urllib.request
    import json

    # Try HTTP status port (gRPC port + 1000)
    leader_reports = {}
    for node_id, addr in config.NODES.items():
        host, port = addr.split(":")
        status_port = str(int(port) + 1000)
        url = f"http://{host}:{status_port}/state"
        try:
            with urllib.request.urlopen(url, timeout=0.8) as resp:
                data = json.loads(resp.read().decode())
                # If a node declares itself leader, return immediately
                if data.get('role') == 'LEADER':
                    return node_id, addr
                lid = data.get('leader_id')
                if lid:
                    leader_reports[lid] = leader_reports.get(lid, 0) + 1
        except Exception:
            continue

    # If a majority of nodes report the same leader_id, prefer that leader
    for lid, cnt in leader_reports.items():
        if cnt >= config.MAJORITY and lid in config.NODES:
            return lid, config.NODES[lid]

    # No safe leader found via HTTP/status consensus; do not perform an AppendEntries probe that can
    # mutate server term state. Return None so caller can retry discovery with a timeout.
    return None, None
    return None, None


def send_command(command, max_attempts=3, backoff=0.5):
    """Send a command to the leader, returning True on success, False on failure.
    Attempts ClientAppend with AppendEntries fallback.
    """
    # Perform reliable leader discovery: verify chosen node actually reports ROLE=LEADER
    discover_attempts = 6
    leader_term = None
    for d_attempt in range(discover_attempts):
        leader_id, leader_addr = find_leader()
        if leader_id is None:
            print("Không tìm thấy leader, thử lại sau")
            time.sleep(0.5)
            continue

        # Query leader state to ensure it claims leadership
        import urllib.request, json
        host, port = leader_addr.split(":")
        url = f"http://{host}:{int(port)+1000}/state"
        try:
            with urllib.request.urlopen(url, timeout=0.8) as r:
                data = json.loads(r.read().decode())
                if data.get('role') != 'LEADER' or data.get('leader_id') != leader_id:
                    # not a stable leader yet, try again
                    time.sleep(0.3)
                    continue
                leader_term = data.get('term')
                print(f"Leader được tìm thấy: Node {leader_id} ({leader_addr})")
                break
        except Exception:
            time.sleep(0.3)
            continue

    if leader_id is None or leader_term is None:
        print("Không có leader ổn định, thử lại sau")
        return False

    channel = grpc.insecure_channel(leader_addr)
    stub = raft_pb2_grpc.RaftServiceStub(channel)

    entry = raft_pb2.LogEntry(term=leader_term, command=command)
    request = raft_pb2.AppendEntriesRequest(
        term=leader_term,
        leader_id=leader_id,
        prev_log_index=-1,
        prev_log_term=0,
        entries=[entry],
        leader_commit=-1
    )

    # Try ClientAppend if available; on UNIMPLEMENTED fallback to AppendEntries
    for attempt in range(max_attempts):
        try:
            resp = stub.ClientAppend(request, timeout=5)
            if resp.success:
                print(f"Lệnh '{command}' commit thành công (term={resp.term})")
                return True
            else:
                print(f"Lệnh '{command}' không được commit (leader term={resp.term}), thử lại... ({attempt+1}/{max_attempts})")
                # re-discover leader and retry
                leader_id, leader_addr = find_leader()
                if leader_addr is None:
                    time.sleep(backoff)
                    continue
                channel = grpc.insecure_channel(leader_addr)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                request.leader_id = leader_id
        except grpc.RpcError as e:
            # If server doesn't implement ClientAppend, fallback to AppendEntries RPC
            if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                try:
                    resp = stub.AppendEntries(request, timeout=5)
                    if resp.success:
                        print(f"Lệnh '{command}' commit thành công (term={resp.term}) [fallback AppendEntries]")
                        return True
                    else:
                        print(f"Lệnh '{command}' không được commit (leader term={resp.term}), thử lại... ({attempt+1}/{max_attempts})")
                        leader_id, leader_addr = find_leader()
                        if leader_addr is None:
                            time.sleep(backoff)
                            continue
                        channel = grpc.insecure_channel(leader_addr)
                        stub = raft_pb2_grpc.RaftServiceStub(channel)
                        request.leader_id = leader_id
                except Exception as ex:
                    print(f"Fallback AppendEntries lỗi: {ex}, thử lại... ({attempt+1}/{max_attempts})")
                    time.sleep(backoff)
                    continue
            else:
                print(f"Lỗi khi gửi lệnh: {e}, thử lại... ({attempt+1}/{max_attempts})")
                time.sleep(backoff)
        except Exception as e:
            print(f"Lỗi khi gửi lệnh: {e}, thử lại... ({attempt+1}/{max_attempts})")
            time.sleep(backoff)
    print("Gửi lệnh thất bại sau nhiều lần thử. Hãy thử lại sau.")
    return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) < 1:
        print(f"Cách dùng: python {os.path.basename(__file__)} COMMAND [ARGS...]")
        sys.exit(1)

    command = " ".join(argv).strip()
    ok = send_command(command)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
