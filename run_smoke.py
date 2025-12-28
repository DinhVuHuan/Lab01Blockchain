import time
import json
import urllib.request
from raft_client import send_command
import config


def probe_states():
    res = {}
    for nid, addr in config.NODES.items():
        host, port = addr.split(":")
        url = f"http://{host}:{int(port)+1000}/state"
        try:
            with urllib.request.urlopen(url, timeout=0.5) as r:
                res[nid] = json.loads(r.read().decode())
        except Exception as e:
            res[nid] = {'error': str(e)}
    return res


def find_stable_leader(poll_interval=0.5, stable_for=3, timeout=30):
    start = time.time()
    last_leader = None
    stable_count = 0
    while time.time() - start < timeout:
        states = probe_states()
        # pick leader_id reported by any node claiming LEADER
        leader_ids = [s.get('leader_id') for s in states.values() if isinstance(s, dict) and s.get('role') == 'LEADER']
        leader = None
        if leader_ids:
            leader = leader_ids[0]
        # fallback: choose most common leader_id
        if not leader:
            reported = [s.get('leader_id') for s in states.values() if isinstance(s, dict) and s.get('leader_id')]
            if reported:
                leader = max(set(reported), key=reported.count)

        print(f"probe leaders: {leader}, states: {[states[i].get('role') if isinstance(states[i],dict) else 'ERR' for i in sorted(states)]}")

        if leader == last_leader and leader is not None:
            stable_count += 1
            if stable_count >= stable_for:
                return leader, states
        else:
            stable_count = 0
            last_leader = leader
        time.sleep(poll_interval)
    return None, states


if __name__ == '__main__':
    print("Waiting for stable leader...")
    # Increase stability requirement for this noisy test environment
    leader, states = find_stable_leader(poll_interval=0.5, stable_for=8, timeout=120)
    if not leader:
        print("No stable leader found. Dumping states:")
        print(states)
        raise SystemExit(1)

    print(f"Stable leader found: {leader}. Waiting a bit to ensure stability...")
    # Wait a couple election timeouts to ensure leader remains
    import config as _c
    time.sleep(_c.ELECTION_TIMEOUT_MIN * 1.5)
    print("Proceeding to send commands to leader.")
    # Use a fixed leader for the test to avoid sending to different leaders
    leader_addr = config.NODES[leader]

    def send_command_to(leader_id, leader_addr, command):
        import raft_pb2, raft_pb2_grpc, urllib.request, json, grpc
        host, port = leader_addr.split(":")
        url = f"http://{host}:{int(port)+1000}/state"
        leader_term = None
        try:
            with urllib.request.urlopen(url, timeout=0.8) as r:
                leader_term = json.loads(r.read().decode()).get('term')
        except Exception:
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
        try:
            # Use ClientAppend to exercise leader-only RPC
            resp = stub.ClientAppend(request, timeout=5)
            print(f"-> sent to leader {leader_id}: {command} (resp.success={resp.success}, term={resp.term})")
            return resp
        except Exception as e:
            print("-> send error", e)
            return None

    commands = ["set k1 1", "set k2 2", "set k3 3"]
    expected_commits = 0
    for c in commands:
        print(f"Sending to leader {leader}: {c}")
        resp = send_command_to(leader, leader_addr, c)
        time.sleep(1.0)
        # probe states to see if commit advanced
        states = probe_states()
        commit_counts = sum(1 for s in states.values() if isinstance(s, dict) and s.get('commit_index', -1) >= 0)
        print("commit_counts after send:", commit_counts)

    print("Waiting for replication/commit to converge...")
    time.sleep(3.0)

    states = probe_states()
    print("Final states:")
    for nid in sorted(states):
        print(nid, states[nid])

    committed = [s for s in states.values() if isinstance(s, dict) and s.get('commit_index', -1) >= 0]
    if committed:
        print("Some nodes have committed entries:")
        for nid in sorted(states):
            st = states[nid]
            if isinstance(st, dict):
                print(nid, 'commit_index=', st.get('commit_index'), 'committed_command=', st.get('committed_command'))
    else:
        print("No commits detected.")
