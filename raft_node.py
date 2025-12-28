# =====================================
# RAFT NODE + gRPC SERVER
# =====================================

import time
import threading
import grpc
import os
from concurrent import futures
from collections import deque

import raft_pb2
import raft_pb2_grpc
import config
from raft_state import RaftState, LogEntry

class RaftNode(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self):
        self.node_id = config.NODE_ID
        if self.node_id not in config.NODES:
            raise ValueError(f"Invalid NODE_ID: {self.node_id}")
        self.address = config.NODES[self.node_id]

        self.state = RaftState(self.node_id)
        self.running = True
        self.server = None
        # peers we intentionally 'blackhole' for simulation of partitions
        self.blackholed_peers = set()

        # Leader replication bookkeeping (initialized when this node becomes leader)
        self.next_index = {}
        self.match_index = {}

        # Telemetry: last several replication errors (for /state visibility)
        self.replication_errors = deque(maxlen=50)

        # Persistent KV store for applied commands
        from kv_store import KVStore
        data_dir = 'data'
        try:
            os.makedirs(data_dir, exist_ok=True)
            self.kv_store = KVStore(os.path.join(data_dir, f'node_{self.node_id}.json'))
        except Exception as e:
            print(f"[Node {self.node_id}] failed to initialize KV store: {e}")
            self.kv_store = None

        # Start apply loop to persist committed entries into KV store
        threading.Thread(target=self.apply_committed_loop, daemon=True).start()

        self.state.reset_election_timeout(min_timeout=config.ELECTION_TIMEOUT_MIN, max_timeout=config.ELECTION_TIMEOUT_MAX)
        print(f"[Node {self.node_id}] initialized at {self.address}")

        # telemetry for peer heartbeats/acks
        import time as _time
        self.last_heartbeat_ack = {pid: 0 for pid in self.state.peers}
        self.peer_failure_counts = {pid: 0 for pid in self.state.peers}

        # Start a tiny HTTP status server (port = gRPC_port + 1000) for state queries and admin actions
        try:
            self.start_status_server()
        except Exception as e:
            print(f"[Node {self.node_id}] failed to start status server: {e}")

        threading.Thread(target=self.bootstrap_and_start, daemon=True).start()

    def bootstrap_and_start(self):
        time.sleep(1)
        self.ping_peers()
        threading.Thread(target=self.election_loop, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()

    def ping_peers(self):
        """Perform a quick AppendEntries probe to detect reachability and record last ack time."""
        for peer_id in self.state.peers:
            try:
                channel = grpc.insecure_channel(config.NODES[peer_id])
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                req = raft_pb2.AppendEntriesRequest(term=self.state.current_term, leader_id=self.node_id, prev_log_index=-1, prev_log_term=0, entries=[], leader_commit=self.state.commit_index)
                resp = stub.AppendEntries(req, timeout=1)
                if getattr(resp, 'success', False):
                    self.last_heartbeat_ack[peer_id] = time.time()
                    self.peer_failure_counts[peer_id] = 0
                    print(f"[Node {self.node_id}] peer {peer_id} reachable (AppendEntries OK)")
                else:
                    self.last_heartbeat_ack[peer_id] = 0
                    print(f"[Node {self.node_id}] peer {peer_id} reachable but returned success=False")
            except Exception as e:
                self.last_heartbeat_ack[peer_id] = 0
                print(f"[Node {self.node_id}] peer {peer_id} not reachable on probe: {e}")

    # ----------------------
    # RPC Handlers
    # ----------------------
    def RequestVote(self, request, context):
        try:
            print(f"[Node {self.node_id}] RPC RequestVote from candidate={request.candidate_id} term={request.term}")
            granted, term = self.state.on_request_vote(request.term, request.candidate_id)
            print(f"[Node {self.node_id}] RequestVote -> vote_granted={granted} term={term}")
            if granted:
                self.state.reset_election_timeout()
            return raft_pb2.RequestVoteResponse(term=term, vote_granted=granted)
        except Exception as e:
            import traceback
            print(f"[Node {self.node_id}] RequestVote handler exception: {e}")
            tb = traceback.format_exc()
            print(tb)
            try:
                with open(f"node-{self.node_id}.log", "a", encoding="utf-8") as lf:
                    lf.write("RequestVote handler exception:\n")
                    lf.write(tb)
                    lf.write("\n---\n")
            except Exception:
                pass
            return raft_pb2.RequestVoteResponse(term=self.state.current_term, vote_granted=False)

    def AppendEntries(self, request, context):
        try:
            # Simulate network partition: if this node has blackholed the leader, reject
            if request.leader_id in self.blackholed_peers:
                print(f"[Node {self.node_id}] rejecting AppendEntries from blackholed leader {request.leader_id}")
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

            entries = [LogEntry(e.term, e.command) for e in request.entries]
            success, term = self.state.on_append_entries(
                request.term, request.leader_id,
                request.prev_log_index, request.prev_log_term,
                entries, request.leader_commit
            )

            if not success:
                # reject if term is old or logs mismatch
                print(f"[Node {self.node_id}] heartbeat/log from {request.leader_id} failed (term {request.term})")
                return raft_pb2.AppendEntriesResponse(term=term, success=False)

            # reset election timer on valid append/heartbeat
            self.state.reset_election_timeout()

            # If this is a client-submitted command (entries present)
            if len(entries) > 0:
                print(f"[Node {self.node_id}] received entries: {[e.command for e in entries]} (from leader {request.leader_id})")

                # Followers should accept entries replicated by the leader (they've been appended in on_append_entries).
                # Leader needs to replicate these further and wait for majority.
                if not self.state.is_leader():
                    # follower: already appended entries in state, accept
                    return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=True)

                # This node is leader: ensure the appended entries are marked with current leader term
                for i in range(len(entries)):
                    self.state.log[len(self.state.log) - len(entries) + i].term = self.state.current_term

                # Try to replicate to majority with retries (leader fast-path)
                index = len(self.state.log) - 1
                prev_index = index - len(entries)
                prev_term = self.state.log[prev_index].term if prev_index >= 0 else 0
                proto_entries = [raft_pb2.LogEntry(term=e.term, command=e.command) for e in entries]

                successes = 1
                max_retries = 3
                backoff = 0.2
                for peer_id in self.state.peers:
                    # skip peers we have 'blackholed' (simulate partition)
                    if peer_id in self.blackholed_peers:
                        print(f"[Node {self.node_id}] skipping peer {peer_id} due to blackhole")
                        continue

                    acked = False
                    for attempt in range(max_retries):
                        try:
                            channel = grpc.insecure_channel(config.NODES[peer_id])
                            stub = raft_pb2_grpc.RaftServiceStub(channel)
                            req = raft_pb2.AppendEntriesRequest(
                                term=self.state.current_term,
                                leader_id=self.node_id,
                                prev_log_index=prev_index,
                                prev_log_term=prev_term,
                                entries=proto_entries,
                                leader_commit=self.state.commit_index
                            )
                            resp = stub.AppendEntries(req, timeout=1)
                            print(f"[Node {self.node_id}] replicate to {peer_id} attempt {attempt+1}: resp.success={getattr(resp,'success',None)} resp.term={getattr(resp,'term',None)}")
                            if resp.success:
                                successes += 1
                                acked = True
                                break
                        except Exception as ex:
                            print(f"[Node {self.node_id}] replicate to {peer_id} attempt {attempt+1} EXCEPTION: {ex}")
                        time.sleep(backoff)
                    if not acked:
                        print(f"[Node {self.node_id}] peer {peer_id} did not ack after {max_retries} attempts")

                # Commit if majority acknowledged
                if successes >= config.MAJORITY:
                    with self.state.lock:
                        old_commit = self.state.commit_index
                        self.state.commit_index = index
                    if self.state.commit_index != old_commit:
                        print(f"[Node {self.node_id}] Entry committed at index {self.state.commit_index}: {self.state.log[self.state.commit_index].command}")
                    return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=True)
                else:
                    print(f"[Node {self.node_id}] replication had only {successes} acknowledgements (need {config.MAJORITY})")
                    return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

            # No entries => heartbeat
            return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=True)
        except Exception as e:
            import traceback
            print(f"[Node {self.node_id}] AppendEntries handler exception:")
            tb = traceback.format_exc()
            print(tb)
            try:
                with open(f"node-{self.node_id}.log", "a", encoding="utf-8") as lf:
                    lf.write("AppendEntries handler exception:\n")
                    lf.write(tb)
                    lf.write("\n---\n")
            except Exception as write_ex:
                print(f"[Node {self.node_id}] failed to write log file: {write_ex}")
            return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

    def replicate_to_peer(self, peer_id, max_replication_steps=10, batch_size=10):
        """Attempt to replicate log entries to a single peer using nextIndex bookkeeping.
        Strategy:
        1) Try sending a reasonably-sized batch from nextIndex (common fast path).
        2) If rejected, perform a bounded binary-search-like probe over prev_index to find a match quickly.
        3) Update matchIndex/nextIndex on success and return True if peer caught up to leader tail.
        Returns True if the peer acked up to current leader log, False otherwise.
        """
        if peer_id in self.blackholed_peers:
            print(f"[Node {self.node_id}] replicate: peer {peer_id} is blackholed -> skip")
            return False

        if peer_id not in self.next_index:
            self.next_index[peer_id] = len(self.state.log)
            self.match_index[peer_id] = -1

        attempts = 0
        # Fast-path and limited probing loop
        while attempts < max_replication_steps:
            attempts += 1
            next_idx = min(self.next_index[peer_id], len(self.state.log))
            prev_index = next_idx - 1
            prev_term = self.state.log[prev_index].term if prev_index >= 0 and prev_index < len(self.state.log) else 0

            # send bounded batch from next_idx
            end = min(len(self.state.log), next_idx + batch_size)
            entries = [raft_pb2.LogEntry(term=e.term, command=e.command) for e in self.state.log[next_idx:end]]

            try:
                channel = grpc.insecure_channel(config.NODES[peer_id])
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                req = raft_pb2.AppendEntriesRequest(
                    term=self.state.current_term,
                    leader_id=self.node_id,
                    prev_log_index=prev_index,
                    prev_log_term=prev_term,
                    entries=entries,
                    leader_commit=self.state.commit_index
                )
                resp = stub.AppendEntries(req, timeout=1)
                print(f"[Node {self.node_id}] replicate_to_peer {peer_id} attempt={attempts} next_idx={next_idx} prev_index={prev_index} entries_sent={len(entries)} resp.success={getattr(resp,'success',None)} resp.term={getattr(resp,'term',None)}")

                # If follower reports a higher term, step down
                if getattr(resp, 'term', None) and resp.term > self.state.current_term:
                    print(f"[Node {self.node_id}] replicate_to_peer {peer_id} sees higher term {resp.term} -> stepping down")
                    # Extra diagnostics: dump stack and debug status at the exact detection point
                    try:
                        import traceback, sys
                        traceback.print_stack(file=sys.stdout)
                        self.state.debug_status()
                    except Exception as ex:
                        print(f"[Node {self.node_id}] failed to print diagnostic stack: {ex}")
                    self.state.become_follower(resp.term)
                    return False

                if resp.success:
                    # update match/next indices based on what we sent
                    last_sent = next_idx + len(entries) - 1 if len(entries) > 0 else next_idx - 1
                    if last_sent >= 0:
                        self.match_index[peer_id] = last_sent
                        self.next_index[peer_id] = last_sent + 1
                    # if we've caught the follower up to leader's tail, success
                    if self.next_index[peer_id] >= len(self.state.log):
                        return True
                    # otherwise, continue sending the next batch
                    continue
                else:
                    # Fallback: binary-search-like probe to find a matching prev_index faster
                    low = 0
                    high = max(0, next_idx - 1)
                    performed_probe = False
                    while low <= high and attempts < max_replication_steps:
                        # Bias towards the right (closer to tail) to find recent matching prefix faster
                        mid = (low + high + 1) // 2
                        attempts += 1
                        performed_probe = True
                        probe_prev = mid - 1
                        probe_prev_term = self.state.log[probe_prev].term if probe_prev >= 0 and probe_prev < len(self.state.log) else 0
                        probe_end = min(len(self.state.log), mid + batch_size)
                        probe_entries = [raft_pb2.LogEntry(term=e.term, command=e.command) for e in self.state.log[mid:probe_end]]
                        try:
                            req = raft_pb2.AppendEntriesRequest(
                                term=self.state.current_term,
                                leader_id=self.node_id,
                                prev_log_index=probe_prev,
                                prev_log_term=probe_prev_term,
                                entries=probe_entries,
                                leader_commit=self.state.commit_index
                            )
                            presp = stub.AppendEntries(req, timeout=1)
                            print(f"[Node {self.node_id}] probe {peer_id} mid={mid} prev={probe_prev} sent={len(probe_entries)} presp.success={getattr(presp,'success',None)} presp.term={getattr(presp,'term',None)}")
                            if getattr(presp, 'term', None) and presp.term > self.state.current_term:
                                print(f"[Node {self.node_id}] probe {peer_id} sees higher term {presp.term} -> stepping down")
                                self.state.become_follower(presp.term)
                                return False

                            if presp.success:
                                last = mid + len(probe_entries) - 1 if len(probe_entries) > 0 else mid - 1
                                if last >= 0:
                                    self.match_index[peer_id] = last
                                    self.next_index[peer_id] = last + 1
                                # if caught up to tail, we're done
                                if self.next_index[peer_id] >= len(self.state.log):
                                    return True
                                # break out of probe to resume catch-up from new next_index
                                break
                            else:
                                # move left in search space
                                high = mid - 1
                                continue
                        except Exception as ex:
                            msg = f"probe {peer_id} exception: {ex}"
                            print(f"[Node {self.node_id}] {msg}")
                            try:
                                self.replication_errors.append(msg)
                            except Exception:
                                pass
                            time.sleep(0.05)
                            continue

                    if not performed_probe:
                        # as a last resort, decrement next_index by one and retry
                        self.next_index[peer_id] = max(0, self.next_index[peer_id] - 1)
                        msg = f"replicate_to_peer {peer_id} mismatch -> next_index now {self.next_index[peer_id]}"
                        print(f"[Node {self.node_id}] {msg}")
                        try:
                            self.replication_errors.append(msg)
                        except Exception:
                            pass
            except Exception as ex:
                msg = f"replicate_to_peer {peer_id} exception: {ex}"
                print(f"[Node {self.node_id}] {msg}")
                try:
                    self.replication_errors.append(msg)
                except Exception:
                    pass
                time.sleep(0.1)
                continue
        return False

    def commit_by_majority(self):
        if not self.state.is_leader():
            return
        N = len(self.state.log) - 1
        for idx in range(self.state.commit_index + 1, N + 1):
            if self.state.log[idx].term != self.state.current_term:
                continue
            count = 1
            for pid in self.match_index:
                if self.match_index.get(pid, -1) >= idx:
                    count += 1
            if count >= config.MAJORITY:
                old = self.state.commit_index
                self.state.commit_index = idx
                if self.state.commit_index != old:
                    print(f"[Node {self.node_id}] Entry committed at index {self.state.commit_index}: {self.state.log[self.state.commit_index].command}")

    def apply_committed_loop(self):
        """Apply committed log entries to the persistent KV store.
        Commands supported (simple):
          set <key> <value>
        """
        while self.running:
            try:
                # apply any newly committed entries
                to_apply = []
                with self.state.lock:
                    last_applied = getattr(self.state, 'last_applied', -1)
                    commit_index = self.state.commit_index
                    if commit_index > last_applied:
                        for idx in range(last_applied + 1, commit_index + 1):
                            if idx < len(self.state.log):
                                to_apply.append((idx, self.state.log[idx]))
                for idx, entry in to_apply:
                    cmd = entry.command
                    # parse simple set command
                    if cmd and cmd.startswith('set '):
                        parts = cmd.split(' ', 2)
                        if len(parts) == 3:
                            _, k, v = parts
                            if self.kv_store:
                                try:
                                    self.kv_store.set(k, v)
                                    print(f"[Node {self.node_id}] applied index {idx}: set {k} = {v}")
                                except Exception as e:
                                    print(f"[Node {self.node_id}] failed to persist {k}: {e}")
                    # update last_applied
                    with self.state.lock:
                        self.state.last_applied = max(getattr(self.state, 'last_applied', -1), idx)
                time.sleep(0.05)
            except Exception as e:
                print(f"[Node {self.node_id}] apply loop exception: {e}")
                time.sleep(0.1)

    def ClientAppend(self, request, context):
        try:
            """Leader-only RPC: client submits a single command (in request.entries[0]).
            Append locally, replicate using nextIndex and wait for majority commit.
            """
            if not self.state.is_leader():
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

            cmd = None
            if request.entries and len(request.entries) > 0:
                cmd = request.entries[0].command
            else:
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

            with self.state.lock:
                entry = LogEntry(self.state.current_term, cmd)
                self.state.log.append(entry)
                index = len(self.state.log) - 1
            print(f"[Node {self.node_id}] appended client command at index {index}: {cmd}")

            # Ensure next_index initial values
            for pid in self.state.peers:
                if pid not in self.next_index:
                    self.next_index[pid] = index + 1
                else:
                    self.next_index[pid] = min(self.next_index[pid], index + 1)

            # Attempt to replicate to peers
            successes = 1
            max_retries = 5
            backoff = 0.5
            prev_index = index - 1
            prev_term = self.state.log[prev_index].term if prev_index >= 0 else 0
            proto_entries = [raft_pb2.LogEntry(term=entry.term, command=entry.command)]

            acked_peers = []
            failed_peers = []

            for peer_id in self.state.peers:
                # skip peers we have 'blackholed' (simulate partition)
                if peer_id in self.blackholed_peers:
                    print(f"[Node {self.node_id}] skipping peer {peer_id} due to blackhole")
                    failed_peers.append(peer_id)
                    continue

                acked = False
                for attempt in range(max_retries):
                    try:
                        channel = grpc.insecure_channel(config.NODES[peer_id])
                        stub = raft_pb2_grpc.RaftServiceStub(channel)
                        req = raft_pb2.AppendEntriesRequest(
                            term=self.state.current_term,
                            leader_id=self.node_id,
                            prev_log_index=prev_index,
                            prev_log_term=prev_term,
                            entries=proto_entries,
                            leader_commit=self.state.commit_index
                        )
                        resp = stub.AppendEntries(req, timeout=2)
                        print(f"[Node {self.node_id}] ClientAppend -> peer {peer_id} attempt {attempt+1} resp.success={getattr(resp,'success',None)} resp.term={getattr(resp,'term',None)}")
                        if resp.success:
                            successes += 1
                            acked = True
                            acked_peers.append(peer_id)
                            break
                        else:
                            print(f"[Node {self.node_id}] peer {peer_id} rejected ClientAppend on attempt {attempt+1}")
                    except Exception as ex:
                        print(f"[Node {self.node_id}] ClientAppend replicate to {peer_id} attempt {attempt+1} EXCEPTION: {ex}")
                    time.sleep(backoff)
                if not acked:
                    print(f"[Node {self.node_id}] peer {peer_id} did not ack client append after {max_retries} attempts")
                    failed_peers.append(peer_id)
                    try:
                        self.replication_errors.append(f"peer {peer_id} failed client append after {max_retries} attempts")
                    except Exception:
                        pass
                else:
                    # record last successful ack time
                    self.last_heartbeat_ack[peer_id] = time.time()
                    self.peer_failure_counts[peer_id] = 0

            if successes >= config.MAJORITY:
                with self.state.lock:
                    old_commit = self.state.commit_index
                    self.state.commit_index = index
                if self.state.commit_index != old_commit:
                    print(f"[Node {self.node_id}] Client command committed at index {self.state.commit_index}: {self.state.log[self.state.commit_index].command}")
                print(f"[Node {self.node_id}] ClientAppend acked_peers={acked_peers} failed_peers={failed_peers} total_successes={successes}")
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=True)
            else:
                print(f"[Node {self.node_id}] client replication had only {successes} acknowledgements (need {config.MAJORITY}) acked_peers={acked_peers} failed_peers={failed_peers}")
                return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)
        except Exception as e:
            import traceback
            print(f"[Node {self.node_id}] ClientAppend handler exception:")
            tb = traceback.format_exc()
            print(tb)
            try:
                with open(f"node-{self.node_id}.log", "a", encoding="utf-8") as lf:
                    lf.write("ClientAppend handler exception:\n")
                    lf.write(tb)
                    lf.write("\n---\n")
            except Exception as write_ex:
                print(f"[Node {self.node_id}] failed to write log file: {write_ex}")
            return raft_pb2.AppendEntriesResponse(term=self.state.current_term, success=False)

    # ----------------------
    # RAFT Loops
    # ----------------------
    def election_loop(self):
        while self.running:
            time.sleep(0.05)
            if self.state.is_leader(): continue
            if self.state.election_timeout_reached():
                self.start_election()

    def start_election(self):
        self.state.become_candidate()
        print(f"[Node {self.node_id}] starting election (term {self.state.current_term})")
        for peer_id in self.state.peers:
            try:
                print(f"[Node {self.node_id}] sending RequestVote to peer {peer_id} (term={self.state.current_term})")
                channel = grpc.insecure_channel(config.NODES[peer_id])
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                request = raft_pb2.RequestVoteRequest(term=self.state.current_term, candidate_id=self.node_id)
                response = stub.RequestVote(request, timeout=1)
                print(f"[Node {self.node_id}] got RequestVote response from {peer_id}: term={response.term} vote_granted={response.vote_granted}")

                if response.term > self.state.current_term:
                    print(f"[Node {self.node_id}] observed higher term {response.term} from {peer_id} -> step down")
                    self.state.become_follower(response.term)
                    return

                if response.vote_granted and self.state.receive_vote():
                    print(f"[Node {self.node_id}] received majority votes -> become leader")
                    self.state.become_leader()
                    # initialize leader replication bookkeeping
                    last_index = len(self.state.log)
                    for pid in self.state.peers:
                        # nextIndex: index of the next entry to send to that server
                        self.next_index[pid] = last_index
                        # matchIndex: highest index known to be replicated on server
                        self.match_index[pid] = -1
                    print(f"[Node {self.node_id}] initialized next_index={self.next_index}")

                    # Append a no-op entry in the new leader's term to establish leadership
                    with self.state.lock:
                        noop = LogEntry(self.state.current_term, "__noop__")
                        self.state.log.append(noop)
                        noop_index = len(self.state.log) - 1
                    print(f"[Node {self.node_id}] appended noop at idx {noop_index} to assert leadership")

                    # try to replicate noop to peers and commit if majority
                    for pid in self.state.peers:
                        try:
                            self.replicate_to_peer(pid)
                        except Exception as e:
                            print(f"[Node {self.node_id}] replicate noop to {pid} exception: {e}")
                    self.commit_by_majority()
                    return
            except Exception as e:
                print(f"[Node {self.node_id}] RequestVote RPC to {peer_id} exception: {e}")
                continue

    def heartbeat_loop(self):
        while self.running:
            time.sleep(config.HEARTBEAT_INTERVAL)
            if not self.state.is_leader(): continue

            # for each peer, either send heartbeat or catch-up replication
            for peer_id in self.state.peers:
                # skip peers we have 'blackholed' (simulate partition)
                if peer_id in self.blackholed_peers:
                    # show quieter heartbeat skipping
                    continue
                try:
                    # attempt to catch the peer up if it is behind
                    ok = self.replicate_to_peer(peer_id)
                    if ok:
                        # Reset failure counter and update last ack time
                        self.peer_failure_counts[peer_id] = 0
                        self.last_heartbeat_ack[peer_id] = time.time()
                    else:
                        # increment failure counter
                        self.peer_failure_counts[peer_id] = self.peer_failure_counts.get(peer_id, 0) + 1
                        if self.peer_failure_counts[peer_id] >= 3:
                            age = None
                            if self.last_heartbeat_ack.get(peer_id):
                                age = time.time() - self.last_heartbeat_ack[peer_id]
                            print(f"[Node {self.node_id}] WARNING: peer {peer_id} failing heartbeats x{self.peer_failure_counts[peer_id]} (last_ack_age={age})")
                except Exception as ex:
                    print(f"[Node {self.node_id}] heartbeat replicate to {peer_id} exception: {ex}")
                    self.peer_failure_counts[peer_id] = self.peer_failure_counts.get(peer_id, 0) + 1
                    continue

    def start_status_server(self):
        """Start a minimal HTTP server that returns JSON state at /state"""
        import json
        import urllib.parse
        from http.server import HTTPServer, BaseHTTPRequestHandler

        host, port = self.address.split(":")
        status_port = str(int(port) + 1000)

        node = self
        state = self.state

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                # Admin endpoints under /admin and read-only status at /state
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                q = urllib.parse.parse_qs(parsed.query)

                if path == '/state':
                    with state.lock:
                        payload = {
                            'role': state.role,
                            'leader_id': state.leader_id,
                            'term': state.current_term,
                            'log_len': len(state.log),
                            'commit_index': state.commit_index,
                            'last_applied': state.last_applied,
                            'blackholed_peers': list(node.blackholed_peers),
                            'next_index': getattr(node, 'next_index', {}),
                            'match_index': getattr(node, 'match_index', {}),
                            'replication_errors': list(node.replication_errors)
                        }
                        # KV snapshot for debugging/durability check
                        try:
                            payload['kv_snapshot'] = node.kv_store.to_dict() if getattr(node, 'kv_store', None) else {}
                        except Exception:
                            payload['kv_snapshot'] = {}

                        if state.commit_index >= 0 and state.commit_index < len(state.log):
                            payload['committed_command'] = state.log[state.commit_index].command
                        else:
                            payload['committed_command'] = None
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(payload).encode())
                    return

                if path.startswith('/admin'):
                    # /admin/disconnect?peers=1,2
                    if path == '/admin/disconnect':
                        peers = q.get('peers', [''])[0]
                        if peers:
                            ids = [int(x) for x in peers.split(',') if x.strip()]
                            for pid in ids:
                                node.blackholed_peers.add(pid)
                            print(f"[Node {node.node_id}] admin: blackholed peers now: {node.blackholed_peers}")
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b'OK')
                            return
                        else:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'Missing peers')
                            return

                    # /admin/reconnect?peers=1,2
                    if path == '/admin/reconnect':
                        peers = q.get('peers', [''])[0]
                        if peers:
                            ids = [int(x) for x in peers.split(',') if x.strip()]
                            for pid in ids:
                                node.blackholed_peers.discard(pid)
                            print(f"[Node {node.node_id}] admin: blackholed peers now: {node.blackholed_peers}")
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b'OK')
                            return
                        else:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'Missing peers')
                            return

                    # /admin/clear
                    if path == '/admin/clear':
                        node.blackholed_peers.clear()
                        print(f"[Node {node.node_id}] admin: cleared blackholes")
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b'OK')
                        return

                    # /admin/shutdown
                    if path == '/admin/shutdown':
                        # gracefully stop the server
                        node.running = False
                        print(f"[Node {node.node_id}] admin: shutdown requested")
                        try:
                            if node.server:
                                node.server.stop(0)
                        except Exception:
                            pass
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b'SHUTDOWN')
                        return

                    # /admin/setterm?term=10
                    if path == '/admin/setterm':
                        term_vals = q.get('term', [''])[0]
                        try:
                            t = int(term_vals)
                            # Guard: refuse accidentally-large terms (likely test/human error)
                            if t >= 1000:
                                print(f"[Node {node.node_id}] admin: setterm rejected large term {t}")
                                self.send_response(400)
                                self.end_headers()
                                self.wfile.write(b'Rejected large term')
                                return
                            with state.lock:
                                state.current_term = t
                                state.role = 'FOLLOWER'
                                state.voted_for = None
                                state.reset_election_timeout()
                            print(f"[Node {node.node_id}] admin: set term to {t}")
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b'OK')
                            return
                        except Exception:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'Bad term')
                            return

                # Not found
                self.send_response(404)
                self.end_headers()
                return

            def log_message(self, format, *args):
                return

        def _serve():
            server = HTTPServer((host, int(status_port)), _Handler)
            print(f"[Node {self.node_id}] status HTTP server listening at {host}:{status_port}")
            server.serve_forever()

        threading.Thread(target=_serve, daemon=True).start()

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    node = RaftNode()
    raft_pb2_grpc.add_RaftServiceServicer_to_server(node, server)
    server.add_insecure_port(node.address)
    # store server so admin endpoints can stop it
    node.server = server
    server.start()
    print(f"[Node {node.node_id}] gRPC server listening at {node.address}")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
