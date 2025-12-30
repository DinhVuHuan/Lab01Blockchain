import time
import threading

import grpc
from concurrent import futures

import raft_pb2
import raft_pb2_grpc

from config import (
    NODE_ID,
    NODES,
    ALL_NODES,
    MAJORITY,
    HEARTBEAT_INTERVAL
)

from raft_state import RaftState


class RaftService(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self, state: RaftState):
        self.state = state

    # -------------------------
    # RPC: RequestVote
    # -------------------------
    def RequestVote(self, request, context):
        vote_granted, term = self.state.on_request_vote(
            request.term, request.candidate_id
        )

        return raft_pb2.RequestVoteResponse(
            term=term,
            vote_granted=vote_granted
        )

    # -------------------------
    # RPC: AppendEntries (Heartbeat)
    # -------------------------
    def AppendEntries(self, request, context):
        success, term = self.state.on_append_entries(
            request.term, request.leader_id,
            request.prev_log_index, request.prev_log_term,
            request.entries, request.leader_commit
        )

        return raft_pb2.AppendEntriesResponse(
            term=term,
            success=success
        )

    def ClientAppend(self, request, context):
        try:
            # Leader-only endpoint for clients
            if not self.state.is_leader():
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

            if not request.entries or len(request.entries) == 0:
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

            cmd = request.entries[0].command
            with self.state.lock:
                entry = raft_pb2.LogEntry(term=self.state.current_term, command=cmd)  # type: ignore
                # Use same LogEntry dataclass as raft_state
                from raft_state import LogEntry as LE
                self.state.log.append(LE(self.state.current_term, cmd))
                index = len(self.state.log) - 1

            successes = 1
            max_retries = 5
            backoff = 0.5
            prev_index = index - 1
            prev_term = self.state.log[prev_index].term if prev_index >= 0 else 0

            for peer_id, stub in self.stubs.items():
                acked = False
                for attempt in range(max_retries):
                    try:
                        req = raft_pb2.AppendEntriesRequest(
                            term=self.state.current_term,
                            leader_id=NODE_ID,
                            prev_log_index=prev_index,
                            prev_log_term=prev_term,
                            entries=[raft_pb2.LogEntry(term=self.state.current_term, command=cmd)],
                            leader_commit=self.state.commit_index
                        )
                        # Give peers a bit more time to respond on loaded systems
                        resp = stub.AppendEntries(req, timeout=2)
                        if resp.success:
                            successes += 1
                            acked = True
                            print(f"[Node {NODE_ID}] peer {peer_id} acked client append (attempt {attempt+1})")
                            break
                        else:
                            print(f"[Node {NODE_ID}] peer {peer_id} rejected client append (attempt {attempt+1})")
                    except Exception as ex:
                        print(f"[Node {NODE_ID}] ClientAppend replicate to {peer_id} attempt {attempt+1} EXCEPTION: {ex}")
                    time.sleep(backoff)
                if not acked:
                    print(f"[Node {NODE_ID}] peer {peer_id} did not ack client append after {max_retries} attempts")

            if successes >= MAJORITY:
                with self.state.lock:
                    old_commit = self.state.commit_index
                    self.state.commit_index = index
                if self.state.commit_index != old_commit:
                    print(f"[Node {NODE_ID}] Client command committed at index {self.state.commit_index}: {self.state.log[self.state.commit_index].command}")
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=True)
            else:
                print(f"[Node {NODE_ID}] client replication had only {successes} acknowledgements (need {MAJORITY})")
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)
        except Exception as e:
            import traceback
            print(f"[Node {NODE_ID}] ClientAppend handler exception:")
            tb = traceback.format_exc()
            print(tb)
            try:
                with open(f"node-{NODE_ID}.log", "a", encoding="utf-8") as lf:
                    lf.write("ClientAppend handler exception:\n")
                    lf.write(tb)
                    lf.write("\n---\n")
            except Exception as write_ex:
                print(f"[Node {NODE_ID}] failed to write log file: {write_ex}")
            return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)


# =====================================
# RAFT NODE (SERVER + CLIENT)
# =====================================

class RaftNode:
    def __init__(self):
        self.state = RaftState()
        self.server = None
        self.channels = {}
        self.stubs = {}

    # -------------------------
    # START GRPC SERVER
    # -------------------------
    def start_server(self):
        self.server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10)
        )

        raft_pb2_grpc.add_RaftServiceServicer_to_server(
            RaftService(self.state),
            self.server
        )

        address = NODES[NODE_ID]
        self.server.add_insecure_port(address)
        self.server.start()

        print(f"[Node {NODE_ID}] gRPC server started at {address}")

    # -------------------------
    # CONNECT TO PEERS
    # -------------------------
    def connect_peers(self):
        for nid in ALL_NODES:
            if nid == NODE_ID:
                continue

            channel = grpc.insecure_channel(NODES[nid])
            stub = raft_pb2_grpc.RaftServiceStub(channel)

            self.channels[nid] = channel
            self.stubs[nid] = stub

    # -------------------------
    # ELECTION LOOP
    # -------------------------
    def election_loop(self):
        while True:
            time.sleep(0.2)

            if self.state.role != "LEADER" and self.state.election_timeout_reached():
                self.start_election()

    def start_election(self):
        self.state.become_candidate()

        votes = 1  # vote cho chính mình

        for peer_id, stub in self.stubs.items():
            try:
                response = stub.RequestVote(
                    raft_pb2.RequestVoteRequest(
                        term=self.state.current_term,
                        candidate_id=NODE_ID
                    ),
                    timeout=1
                )

                if response.vote_granted:
                    votes += 1

                if response.term > self.state.current_term:
                    self.state.become_follower(response.term)
                    return

            except Exception:
                continue

        if votes >= MAJORITY:
            self.state.become_leader()

    # -------------------------
    # HEARTBEAT LOOP
    # -------------------------
    def heartbeat_loop(self):
        while True:
            time.sleep(HEARTBEAT_INTERVAL)

            if self.state.role != "LEADER":
                continue

            for peer_id, stub in self.stubs.items():
                try:
                    stub.AppendEntries(
                        raft_pb2.AppendEntriesRequest(
                            term=self.state.current_term,
                            leader_id=NODE_ID,
                            prev_log_index=-1,
                            prev_log_term=0,
                            entries=[],
                            leader_commit=self.state.commit_index
                        ),
                        timeout=1
                    )
                except Exception:
                    continue

    # -------------------------
    # RUN NODE
    # -------------------------
    def run(self):
        self.start_server()
        time.sleep(1)  # chờ các node khác lên
        self.connect_peers()

        threading.Thread(target=self.election_loop, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()

        while True:
            time.sleep(5)
            self.state.debug_status()
