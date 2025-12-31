"""
Lightweight functional tests for `replicate_to_peer` using a fake self object (no RaftNode thread startup).
"""
import raft_pb2_grpc
from raft_node import RaftNode
from raft_state import LogEntry

original_stub = raft_pb2_grpc.RaftServiceStub

class FakeResp:
    def __init__(self, term, success=True):
        self.term = term
        self.success = success

class FakeStubProbeSuccess:
    def __init__(self, channel):
        pass
    def AppendEntries(self, req, timeout=None):
        # accept when prev index == 2
        prev = req.prev_log_index
        if prev == 2:
            return FakeResp(req.term, True)
        else:
            return FakeResp(req.term, False)

class FakeStubHigherTerm:
    def __init__(self, channel):
        pass
    def AppendEntries(self, req, timeout=None):
        return FakeResp(req.term + 10, False)


def make_fake_self():
    class S:
        def __init__(self):
            self.node_id = 999
            self.blackholed_peers = set()
            self.next_index = {}
            self.match_index = {}
            class St:
                pass
            self.state = St()
            self.state.current_term = 1
            self.state.commit_index = -1
            self.state.log = [LogEntry(1, '__noop__') for _ in range(6)]
            self.state.peers = [42]
            def become_follower(term):
                self.state.current_term = term
                self.state.role = 'FOLLOWER'
            self.state.become_follower = become_follower
    return S()


def test_probe_success():
    fake = make_fake_self()
    peer = 42
    # ensure peer address exists for the probe (no network used thanks to FakeStub)
    import config as _c
    orig_nodes = dict(_c.NODES)
    try:
        _c.NODES[peer] = '127.0.0.1:5020'
        fake.next_index[peer] = 6
        fake.match_index[peer] = -1
        raft_pb2_grpc.RaftServiceStub = FakeStubProbeSuccess
        ok = RaftNode.replicate_to_peer(fake, peer, max_replication_steps=10, batch_size=1)
        raft_pb2_grpc.RaftServiceStub = original_stub
        assert fake.match_index[peer] >= 2
    finally:
        _c.NODES.clear()
        _c.NODES.update(orig_nodes)


def test_higher_term():
    fake = make_fake_self()
    fake.state.current_term = 5
    peer = 42
    import config as _c
    orig_nodes = dict(_c.NODES)
    try:
        _c.NODES[peer] = '127.0.0.1:5020'
        fake.next_index[peer] = 3
        raft_pb2_grpc.RaftServiceStub = FakeStubHigherTerm
        ok = RaftNode.replicate_to_peer(fake, peer, max_replication_steps=3, batch_size=1)
        raft_pb2_grpc.RaftServiceStub = original_stub
        assert not ok and fake.state.current_term > 5
    finally:
        _c.NODES.clear()
        _c.NODES.update(orig_nodes)

if __name__ == '__main__':
    a = test_probe_success()
    b = test_higher_term()
    if a and b:
        print('All lightweight replicate_to_peer tests: PASS')
    else:
        print('Some tests failed')
