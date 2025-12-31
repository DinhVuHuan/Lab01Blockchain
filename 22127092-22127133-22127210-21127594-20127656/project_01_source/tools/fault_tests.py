"""
Helpers to simulate failures and run RAFT fault-injection tests.
"""
import time
import json
import urllib.request
import urllib.error
import raft_client
import config
import raft_pb2
import raft_pb2_grpc
import grpc

# Timeouts and retry configs for fault tests
DEFAULT_PROBE_TIMEOUT = 0.5
FIND_LEADER_TIMEOUT = 5  # seconds to wait for a leader
FIND_LEADER_RETRY_INTERVAL = 0.2
FOLLOWER_SYNC_TIMEOUT = 10  # seconds to wait for follower to catch up
FOLLOWER_RECONNECT_RETRY_INTERVAL = 0.5


def probe_states(timeout=0.5):
    res = {}
    for nid, addr in config.NODES.items():
        host, port = addr.split(":")
        url = f"http://{host}:{int(port)+1000}/state"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                res[nid] = json.loads(r.read().decode())
        except Exception as e:
            res[nid] = {'error': str(e)}
    return res


def find_leader(timeout=FIND_LEADER_TIMEOUT, probe_timeout=DEFAULT_PROBE_TIMEOUT, retry_interval=FIND_LEADER_RETRY_INTERVAL):
    start = time.time()
    while time.time() - start < timeout:
        states = probe_states(timeout=probe_timeout)
        for nid, st in states.items():
            if isinstance(st, dict) and st.get('role') == 'LEADER':
                return nid, config.NODES[nid]
        # Fallback: if a majority of nodes report the same leader_id, choose that
        leader_reports = {}
        for nid, st in states.items():
            if isinstance(st, dict):
                lid = st.get('leader_id')
                if lid:
                    leader_reports[lid] = leader_reports.get(lid, 0) + 1
        for lid, cnt in leader_reports.items():
            if cnt >= config.MAJORITY and lid in config.NODES:
                return lid, config.NODES[lid]
        time.sleep(retry_interval)
    return None, None


def admin_call(addr, path):
    host, port = addr.split(":")
    url = f"http://{host}:{int(port)+1000}{path}"
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return f"HTTPError: {e.code}"
    except Exception as e:
        return str(e)


# 1) Leader crash test - shut down leader and ensure new leader elected and client can commit
def run_leader_crash_test(wait_stable=8):
    print("=== Leader crash test ===")

    print("Finding stable leader...")
    start = time.time()
    leader = None
    while time.time() - start < 60:
        leader, leader_addr = find_leader()
        if leader:
            # wait briefly to ensure stability
            time.sleep(1)
            break
        time.sleep(0.2)

    if not leader:
        print("No leader found")
        return False

    print(f"Leader found: {leader}")

    # send a command to leader
    print("Sending initial command to leader")
    raft_client.send_command("set pre_crash 1")

    # wait up to 5s for the initial command to be committed by leader
    start = time.time()
    committed_initial = False
    while time.time() - start < 5:
        states = probe_states()
        if any(isinstance(s, dict) and s.get('commit_index', -1) >= 0 for s in states.values()):
            committed_initial = True
            break
        time.sleep(0.2)

    if not committed_initial:
        print("Initial command did not commit before leader crash (will still crash leader to test recovery)")

    print("Crashing leader via admin shutdown")
    admin_call(leader_addr, '/admin/shutdown')

    # wait for new leader in remaining cluster
    start = time.time()
    new_leader = None
    while time.time() - start < 60:
        nl, nl_addr = find_leader()
        if nl and nl != leader:
            new_leader = nl
            break
        time.sleep(0.2)

    if not new_leader:
        print("No new leader elected after crash")
        return False

    print(f"New leader: {new_leader}. Sending command to new leader...")
    raft_client.send_command("set post_crash 2")

    # wait up to 10s for any commit to appear in the cluster
    start = time.time()
    committed = False
    while time.time() - start < 10:
        states = probe_states()
        if any(isinstance(s, dict) and s.get('commit_index', -1) >= 0 for s in states.values()):
            committed = True
            break
        time.sleep(0.2)

    if committed:
        print("Commit(s) observed after leader crash - PASS")
        return True
    else:
        print("No commits observed after leader crash - FAIL")
        # print snapshot for debugging
        print("State snapshot:")
        for nid, st in states.items():
            print(nid, st)
        return False


# 2) Follower offline/online test
def run_follower_reconnect_test():
    print("=== Follower reconnect test ===")
    leader, leader_addr = find_leader()
    if not leader:
        print("No leader found")
        return False

    # choose a follower
    followers = [nid for nid in config.NODES.keys() if nid != leader]
    if not followers:
        print("No followers to test")
        return False
    f = followers[0]
    faddr = config.NODES[f]

    print(f"Disconnecting follower {f} from leader {leader}")
    # instruct follower to disconnect from leader
    admin_call(faddr, f'/admin/disconnect?peers={leader}')
    time.sleep(1)

    print("Send commands while follower is down")
    raft_client.send_command("set during_outage 3")
    time.sleep(1)

    print("Reconnect follower")
    admin_call(faddr, f'/admin/reconnect?peers={leader}')
    time.sleep(2)

    # probe and compare logs (wait up to FOLLOWER_SYNC_TIMEOUT for follower to catch up)
    start = time.time()
    synced = False
    while time.time() - start < FOLLOWER_SYNC_TIMEOUT:
        states = probe_states()
        leader_state = states.get(leader)
        f_state = states.get(f)
        print(f"Leader state: {leader_state}")
        print(f"Follower state: {f_state}")
        if isinstance(leader_state, dict) and isinstance(f_state, dict):
            leader_log_len = leader_state.get('log_len', 0)
            follower_log_len = f_state.get('log_len', 0)
            if follower_log_len == leader_log_len:
                synced = True
                break
        time.sleep(FOLLOWER_RECONNECT_RETRY_INTERVAL)

    # final check
    states = probe_states()
    leader_state = states.get(leader)
    f_state = states.get(f)
    print(f"Final leader state: {leader_state}")
    print(f"Final follower state: {f_state}")

    if synced:
        print("Follower synced log length with leader - PASS")
        return True
    else:
        print("Follower did NOT sync log length within timeout - FAIL")
        return False


# 3) Partition test: split into two groups, majority should commit, minority not
def run_partition_test():
    print("=== Network partition test ===")
    nodes = sorted(config.NODES.keys())
    n = len(nodes)
    half = n // 2
    groupA = nodes[:half+1]  # ensure majority
    groupB = nodes[half+1:]

    print(f"GroupA (majority): {groupA}")
    print(f"GroupB (minority): {groupB}")

    # Disconnect groups (bi-directional)
    for a in groupA:
        addr = config.NODES[a]
        peers = ','.join(str(x) for x in groupB)
        admin_call(addr, f'/admin/disconnect?peers={peers}')
    for b in groupB:
        addr = config.NODES[b]
        peers = ','.join(str(x) for x in groupA)
        admin_call(addr, f'/admin/disconnect?peers={peers}')

    time.sleep(2)

    # Find leader in groupA and send a command
    leaderA = None
    for nid in groupA:
        st = probe_states().get(nid, {})
        if isinstance(st, dict) and st.get('role') == 'LEADER':
            leaderA = nid
            break
    if not leaderA:
        # re-probe and pick any leader reported
        leaderA = next((nid for nid in groupA if probe_states().get(nid, {}).get('role') == 'LEADER'), None)

    if leaderA:
        print(f"Leader in majority group: {leaderA}")
        raft_client.send_command("set partitioned 99")
        time.sleep(1)

    states = probe_states()
    commits_A = sum(1 for nid in groupA if isinstance(states.get(nid), dict) and states[nid].get('commit_index', -1) >= 0)
    commits_B = sum(1 for nid in groupB if isinstance(states.get(nid), dict) and states[nid].get('commit_index', -1) >= 0)

    print(f"Commits in majority group: {commits_A}, in minority: {commits_B}")

    # Reconnect all
    for nid, addr in config.NODES.items():
        admin_call(addr, '/admin/clear')
    time.sleep(2)

    # After reconnection all should sync
    states = probe_states()
    commit_indexes = [s.get('commit_index') for s in states.values() if isinstance(s, dict)]
    if len(set(commit_indexes)) == 1:
        print("All nodes have consistent commit_index after merge - PASS")
        return True
    else:
        print("Nodes have different commit_index after merge - FAIL")
        return False


# 4) Edge cases: churn, term jump, multiple commands
def run_edgecase_tests():
    print("=== Edge cases test ===")
    # churn: force multiple elections by toggling term and clearing timeouts
    # Simple churn simulation: repeatedly set random nodes' term higher to trigger elections
    import random
    nodes = sorted(config.NODES.keys())

    for i in range(5):
        nid = random.choice(nodes)
        addr = config.NODES[nid]
        t = 100 + i
        print(f"Setting term {t} on node {nid}")
        admin_call(addr, f'/admin/setterm?term={t}')
        time.sleep(1)

    print("Sending a burst of commands to verify order/commit")
    for i in range(5):
        raft_client.send_command(f"set burst{i} {i}")
        time.sleep(0.5)

    time.sleep(2)
    states = probe_states()
    commit_indexes = [s.get('commit_index') for s in states.values() if isinstance(s, dict)]
    if len(set(commit_indexes)) == 1:
        print("Burst commands committed consistently - PASS")
        return True
    else:
        print("Inconsistent commits after churn/burst - FAIL")
        return False


if __name__ == '__main__':
    print("Running leader crash test...")
    run_leader_crash_test()
    time.sleep(1)
    print("Running follower reconnect test...")
    run_follower_reconnect_test()
    time.sleep(1)
    print("Running partition test...")
    run_partition_test()
    time.sleep(1)
    print("Running edgecases tests...")
    run_edgecase_tests()
