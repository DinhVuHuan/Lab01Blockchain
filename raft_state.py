import threading
import time
import random
from config import NODES, MAJORITY, FOLLOWER, CANDIDATE, LEADER, ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX

class LogEntry:
    def __init__(self, term, command):
        self.term = term
        self.command = command

class RaftState:
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.peers = [nid for nid in NODES.keys() if nid != node_id]

        # Persistent state
        self.current_term = 0
        self.voted_for = None

        # Volatile state
        self.role = FOLLOWER
        self.leader_id = None

        # Election
        self.votes_received = 0
        self.reset_election_timeout()

        # Log
        self.log = []
        self.commit_index = -1
        self.last_applied = -1

        # Concurrency
        self.lock = threading.Lock()

    def reset_election_timeout(self, min_timeout=None, max_timeout=None):
        if min_timeout is None:
            min_timeout = ELECTION_TIMEOUT_MIN
        if max_timeout is None:
            max_timeout = ELECTION_TIMEOUT_MAX
        self.election_deadline = time.time() + random.uniform(min_timeout, max_timeout)

    def election_timeout_reached(self):
        return time.time() >= self.election_deadline

    # Role checkers
    def is_leader(self):
        return self.role == LEADER
    def is_candidate(self):
        return self.role == CANDIDATE
    def is_follower(self):
        return self.role == FOLLOWER

    # Role transitions
    def become_follower(self, term: int, leader_id=None):
        with self.lock:
            changed = self.role != FOLLOWER or self.current_term != term
            self.role = FOLLOWER
            self.current_term = term
            self.leader_id = leader_id
            self.votes_received = 0
            self.voted_for = None
            self.reset_election_timeout()
        # Instrumentation: detect unusually large term values and capture a stack trace
        if term >= 1000:
            import traceback, sys
            print(f"[Node {self.node_id}] WARNING: large term set to {term} in become_follower")
            traceback.print_stack(file=sys.stdout)
            # Also dump debug status to help with diagnosis
            self.debug_status()
        if changed:
            print(f"[Node {self.node_id}] -> FOLLOWER (term={term}, leader={leader_id})")

    def become_candidate(self):
        with self.lock:
            self.role = CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.votes_received = 1
            self.reset_election_timeout()
        # Instrumentation: detect unusually large term values and capture a stack trace
        if self.current_term >= 1000:
            import traceback, sys
            print(f"[Node {self.node_id}] WARNING: large term incremented to {self.current_term} in become_candidate")
            traceback.print_stack(file=sys.stdout)
            self.debug_status()
        print(f"[Node {self.node_id}] -> CANDIDATE (term={self.current_term})")

    def become_leader(self):
        with self.lock:
            self.role = LEADER
            self.leader_id = self.node_id
        print(f"🎉 [Node {self.node_id}] ELECTED LEADER (term={self.current_term})")

    # Election logic
    def receive_vote(self):
        with self.lock:
            self.votes_received += 1
            print(f"[Node {self.node_id}] votes_received={self.votes_received}/{MAJORITY}")
            return self.votes_received >= MAJORITY

    # RPC handlers
    def on_request_vote(self, term, candidate_id):
        with self.lock:
            if term < self.current_term:
                return False, self.current_term
            if term > self.current_term:
                self.current_term = term
                self.voted_for = None
                self.role = FOLLOWER
                # Instrumentation: detect unusually large incoming term
                if term >= 1000:
                    import traceback, sys
                    print(f"[Node {self.node_id}] WARNING: on_request_vote received large term {term} from candidate {candidate_id}")
                    traceback.print_stack(file=sys.stdout)
                    self.debug_status()
            if self.voted_for in (None, candidate_id):
                self.voted_for = candidate_id
                self.reset_election_timeout()
                print(f"[Node {self.node_id}] voted for {candidate_id} (term={term})")
                return True, self.current_term
            return False, self.current_term

    def on_append_entries(self, term, leader_id, prev_log_index=None, prev_log_term=None, entries=None, leader_commit=None):
        with self.lock:
            if term < self.current_term:
                return False, self.current_term

            if term > self.current_term or self.role != FOLLOWER:
                self.current_term = term
                self.role = FOLLOWER
                self.voted_for = None
                # Instrumentation: detect unusually large incoming term
                if term >= 1000:
                    import traceback, sys
                    print(f"[Node {self.node_id}] WARNING: on_append_entries received large term {term} from leader {leader_id}")
                    traceback.print_stack(file=sys.stdout)
                    self.debug_status()

            # Leader update
            leader_changed = self.leader_id != leader_id
            self.leader_id = leader_id
            self.reset_election_timeout()

            # Log replication
            if entries is not None and len(entries) > 0:
                if prev_log_index is not None and prev_log_index >= 0:
                    if prev_log_index >= len(self.log) or self.log[prev_log_index].term != prev_log_term:
                        print(f"[Node {self.node_id}] append_entries: prev_log mismatch (prev_index={prev_log_index}, prev_term={prev_log_term}, log_len={len(self.log)})")
                        return False, self.current_term
                for i, e in enumerate(entries):
                    idx = prev_log_index + 1 + i if prev_log_index is not None else i
                    if idx < len(self.log):
                        print(f"[Node {self.node_id}] overwrite log idx {idx} with {e.command} (term {e.term})")
                        self.log[idx] = e
                    else:
                        print(f"[Node {self.node_id}] append log idx {idx}: {e.command} (term {e.term})")
                        self.log.append(e)

            # Commit
            if leader_commit is not None:
                self.commit_index = min(leader_commit, len(self.log) - 1)

        if leader_changed:
            print(f"[Node {self.node_id}] recognized leader {leader_id} (term={term})")
        return True, self.current_term

    def debug_status(self):
        """Print current internal state for debugging."""
        with self.lock:
            print(f"[Node {self.node_id}] state=term:{self.current_term} role:{self.role} voted_for:{self.voted_for} leader:{self.leader_id} log_len:{len(self.log)} commit_index:{self.commit_index}")
