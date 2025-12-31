# =====================================
# RAFT CLIENT (CLI wrapper for tests)
# =====================================

import os
import grpc
import raft_pb2
import raft_pb2_grpc
import config
import sys
import time

# Prefer the more robust implementation in `raft_client.py`. This CLI simply delegates to it
# and falls back to a minimal ClientAppend/AppendEntries attempt if `raft_client` import fails.

def find_leader():
    try:
        import raft_client
        return raft_client.find_leader()
    except Exception:
        # Lightweight fallback: probe HTTP /state endpoints
        import urllib.request, json
        leader_reports = {}
        for node_id, addr in config.NODES.items():
            host, port = addr.split(":")
            status_port = str(int(port) + 1000)
            url = f"http://{host}:{status_port}/state"
            try:
                with urllib.request.urlopen(url, timeout=0.8) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get('role') == 'LEADER':
                        return node_id, addr
                    lid = data.get('leader_id')
                    if lid:
                        leader_reports[lid] = leader_reports.get(lid, 0) + 1
            except Exception:
                continue
        for lid, cnt in leader_reports.items():
            if cnt >= config.MAJORITY and lid in config.NODES:
                return lid, config.NODES[lid]
    return None, None


def send_command(command, max_attempts=3, backoff=0.5):
    """Delegate to `raft_client.send_command` when available; otherwise perform a minimal
    ClientAppend (with AppendEntries fallback) using the discovered leader's term."""
    try:
        import raft_client
        return raft_client.send_command(command, max_attempts=max_attempts, backoff=backoff)
    except Exception as e:
        print(f"Falling back to local send_command: {e}")

    leader_id, leader_addr = find_leader()
    if leader_id is None:
        print("Không tìm thấy leader, thử lại sau")
        return False

    # Try to query leader term via /state
    leader_term = None
    try:
        import urllib.request, json
        host, port = leader_addr.split(":")
        url = f"http://{host}:{int(port)+1000}/state"
        with urllib.request.urlopen(url, timeout=1) as r:
            data = json.loads(r.read().decode())
            leader_term = data.get('term')
    except Exception:
        pass
    if leader_term is None:
        leader_term = 0

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

    # Prefer ClientAppend RPC (leader-side handler), fallback to AppendEntries if UNIMPLEMENTED.
    try:
        resp = stub.ClientAppend(request, timeout=5)
        if getattr(resp, 'success', False):
            print(f"Lệnh '{command}' commit thành công (term={resp.term})")
            return True
        else:
            print(f"Lệnh '{command}' không được commit (leader term={resp.term})")
            return False
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            try:
                resp = stub.AppendEntries(request, timeout=5)
                if getattr(resp, 'success', False):
                    print(f"Lệnh '{command}' commit thành công (term={resp.term}) [fallback AppendEntries]")
                    return True
                else:
                    print(f"Lệnh '{command}' không được commit (leader term={resp.term})")
                    return False
            except Exception as ex:
                print(f"Fallback AppendEntries lỗi: {ex}")
                return False
        else:
            print(f"Lỗi khi gửi lệnh: {e}")
            return False
    except Exception as ex:
        print(f"Lỗi khi gửi lệnh: {ex}")
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
