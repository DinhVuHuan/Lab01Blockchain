import raft_pb2
import raft_pb2_grpc

class RaftRPCService(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self, raft_state):
        self.state = raft_state

    # -----------------------------
    # RequestVote RPC
    # -----------------------------
    def RequestVote(self, request, context):
        with self.state.lock:
            # Nếu term nhỏ hơn → từ chối
            if request.term < self.state.current_term:
                return raft_pb2.RequestVoteResponse(
                    term=self.state.current_term,
                    vote_granted=False
                )

            # Nếu term lớn hơn → cập nhật
            if request.term > self.state.current_term:
                self.state.become_follower(request.term)

            # Chưa vote hoặc đã vote cho candidate này
            if (
                self.state.voted_for is None or
                self.state.voted_for == request.candidate_id
            ):
                self.state.voted_for = request.candidate_id
                self.state.reset_election_timeout()

                return raft_pb2.RequestVoteResponse(
                    term=self.state.current_term,
                    vote_granted=True
                )

            return raft_pb2.RequestVoteResponse(
                term=self.state.current_term,
                vote_granted=False
            )

    # -----------------------------
    # AppendEntries RPC (Heartbeat)
    # -----------------------------
    def AppendEntries(self, request, context):
        with self.state.lock:
            if request.term < self.state.current_term:
                return raft_pb2.AppendEntriesResponse(
                    term=self.state.current_term,
                    success=False
                )

            # Nhận heartbeat hợp lệ
            self.state.become_follower(request.term)
            self.state.leader_id = request.leader_id
            self.state.reset_election_timeout()

            return raft_pb2.AppendEntriesResponse(
                term=self.state.current_term,
                success=True
            )
