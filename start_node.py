# start_node.py
# Start a single RAFT node in its own process for persistent testing

import sys
import time
import grpc
from concurrent import futures
import config
import raft_pb2
import raft_pb2_grpc
from raft_node import RaftNode

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python start_node.py NODE_ID')
        sys.exit(1)

    node_id = int(sys.argv[1])
    config.NODE_ID = node_id

    node = RaftNode()
    # Redirect stdout/stderr to per-node log file for debugging in multi-process tests
    try:
        logf = open(f"node-{node_id}.log", "a", encoding="utf-8")
        import sys as _sys
        _sys.stdout = logf
        _sys.stderr = logf
        print(f"[Node {node_id}] logging to node-{node_id}.log")
    except Exception as e:
        print(f"[Node {node_id}] failed to open log file: {e}")

    # Try multiple address variants to handle platform-specific binding issues (127.0.0.1 vs localhost vs 0.0.0.0)
    host, port = node.address.split(":")
    candidates = [node.address, node.address.replace('127.0.0.1', 'localhost'), node.address.replace('127.0.0.1', '0.0.0.0')]
    bound = False

    for addr in candidates:
        try:
            # create a fresh server instance per candidate so we can stop it if healthcheck fails
            server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
            raft_pb2_grpc.add_RaftServiceServicer_to_server(node, server)
            port_bound = server.add_insecure_port(addr)
            if not port_bound:
                print(f"[Node {node.node_id}] add_insecure_port returned 0 for {addr} (bind failed)")
                continue

            server.start()
            # quick healthcheck: try to call AppendEntries on self
            try:
                import grpc as _grpc
                # When the server binds to 0.0.0.0, connecting to 0.0.0.0 as a client is invalid.
                # Use 127.0.0.1 for health checks so we correctly verify local reachability.
                h, p = addr.split(':')
                health_addr = f"127.0.0.1:{p}"
                channel = _grpc.insecure_channel(health_addr)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                req = raft_pb2.AppendEntriesRequest(term=0, leader_id=0, prev_log_index=-1, prev_log_term=0, entries=[], leader_commit=-1)
                resp = stub.AppendEntries(req, timeout=1)
                # if rpc succeeded, treat bind as successful; prefer client-reachable addr
                node.address = health_addr
                bound = True
                break
            except Exception as e:
                print(f"[Node {node.node_id}] healthcheck for {addr} failed: {e}")
                try:
                    server.stop(0)
                except Exception:
                    pass
                continue
        except Exception as e:
            print(f"[Node {node.node_id}] failed to bind {addr}: {e}")
            continue

    if not bound:
        raise RuntimeError(f"Failed to bind gRPC server for node {node.node_id} on any candidate address")

    print(f"[Node {node.node_id}] gRPC server listening at {node.address}")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print(f"[Node {node.node_id}] shutting down...")
        server.stop(0)