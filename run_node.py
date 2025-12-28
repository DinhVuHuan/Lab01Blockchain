# =====================================
# RUN MULTI RAFT NODES (5 NODES LOCAL)
# =====================================

import threading
import time
from concurrent import futures
import grpc

import config
import raft_pb2_grpc
from raft_node import RaftNode


def start_node(node_id: int):
    """Khởi chạy một node RAFT với node_id cụ thể"""
    try:
        # Set NODE_ID trước khi tạo RaftNode
        config.NODE_ID = node_id
        node = RaftNode()

        # gRPC server
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        raft_pb2_grpc.add_RaftServiceServicer_to_server(node, server)
        server.add_insecure_port(node.address)
        server.start()
        print(f"[Node {node.node_id}] gRPC server listening at {node.address}")

        server.wait_for_termination()
    except Exception as e:
        print(f"[Node {node_id}] failed to start: {e}")


if __name__ == "__main__":
    threads = []

    # Khởi tạo tất cả node trong config.NODES
    for node_id in config.NODES.keys():
        t = threading.Thread(target=start_node, args=(node_id,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.5)  # stagger để tránh race condition khi startup

    print("All RAFT nodes are starting...")

    # Giữ main thread chạy
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down all RAFT nodes...")
