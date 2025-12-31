"""
Unit tests for replicate_to_peer behavior using a Fake RaftServiceStub.
These are lightweight, run in-process, and do not require starting a full cluster.
"""
import time
import raft_pb2_grpc
import raft_pb2
import config
from raft_node import RaftNode
from raft_state import LogEntry

original_stub = raft_pb2_grpc.RaftServiceStub

class FakeResp:
    def __init__(self, term, success=True):
        self.term = term
        self.success = success

class FakeStubProbeSuccess:
    """Simulate a follower that only accepts when prev_log_index == 2 (i.e., has prefix up to index 2)."""
    def __init__(self, channel):
        pass
    def AppendEntries(self, req, timeout=None):
        prev = req.prev_log_index
        # If prev is 2 or less, succeed only when prev==2
        if prev == 2:
            return FakeResp(req.term, True)
        else:
            return FakeResp(req.term, False)

class FakeStubHigherTerm:
    def __init__(self, channel):
        pass
    def AppendEntries(self, req, timeout=None):
        # Always respond with higher term to force leader to step down
        return FakeResp(req.term + 5, False)


def test_probe_success_unit():
    # ensure we restore config after the test to avoid polluting other tests
    orig_nodes = dict(config.NODES)
    orig_node_id = config.NODE_ID
    try:
        cfg_id = 10
        config.NODES[cfg_id] = "127.0.0.1:5010"
        config.NODE_ID = cfg_id

        node = RaftNode()
        # make node leader and set a long log
        node.state.role = config.LEADER
        node.state.current_term = 1
        node.state.log = [LogEntry(1, '__noop__') for _ in range(6)]  # indices 0..5

        # peer id to test
        peer = 20
        config.NODES[peer] = "127.0.0.1:5020"
        node.state.peers = [peer]

        # monkeypatch stub
        raft_pb2_grpc.RaftServiceStub = FakeStubProbeSuccess

        # set next_index initially at tail (6) -> replicate_to_peer should probe and find prev=2
        node.next_index[peer] = 6
        node.match_index[peer] = -1

        ok = node.replicate_to_peer(peer, max_replication_steps=10, batch_size=1)

        raft_pb2_grpc.RaftServiceStub = original_stub

        # cleanup: stop background loops
        node.running = False

        # ensure we discovered a matching prefix (at least index 2)
        assert node.match_index[peer] >= 2
    finally:
        # attempt to shutdown status server to avoid polluting other tests
        try:
            import urllib.request
            host, port = config.NODES[cfg_id].split(":")
            urllib.request.urlopen(f"http://{host}:{int(port)+1000}/admin/shutdown", timeout=1)
        except Exception:
            pass
        # restore original config to avoid affecting other tests
        config.NODES.clear()
        config.NODES.update(orig_nodes)
        config.NODE_ID = orig_node_id


def test_higher_term_unit():
    orig_nodes = dict(config.NODES)
    orig_node_id = config.NODE_ID
    try:
        cfg_id = 11
        config.NODES[cfg_id] = "127.0.0.1:5011"
        config.NODE_ID = cfg_id

        node = RaftNode()
        node.state.role = config.LEADER
        node.state.current_term = 10
        node.state.log = [LogEntry(10, '__noop__') for _ in range(3)]

        peer = 30
        config.NODES[peer] = "127.0.0.1:5030"
        node.state.peers = [peer]

        raft_pb2_grpc.RaftServiceStub = FakeStubHigherTerm

        node.next_index[peer] = 3
        node.match_index[peer] = -1

        ok = node.replicate_to_peer(peer, max_replication_steps=3, batch_size=1)

        raft_pb2_grpc.RaftServiceStub = original_stub

        # cleanup
        node.running = False

        # node should step down
        assert not ok and node.state.role == config.FOLLOWER and node.state.current_term > 10
    finally:
        # attempt to shutdown status server
        try:
            import urllib.request
            host, port = config.NODES[cfg_id].split(":")
            urllib.request.urlopen(f"http://{host}:{int(port)+1000}/admin/shutdown", timeout=1)
        except Exception:
            pass
        config.NODES.clear()
        config.NODES.update(orig_nodes)
        config.NODE_ID = orig_node_id


if __name__ == '__main__':
    all_ok = True
    all_ok &= run_probe_success_test()
    time.sleep(0.1)
    all_ok &= run_higher_term_test()
    if all_ok:
        print("All replicate_to_peer unit tests: PASS")
    else:
        print("Some replicate_to_peer unit tests: FAIL")
