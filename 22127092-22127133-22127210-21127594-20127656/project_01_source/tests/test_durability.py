"""
Durability test: start cluster, commit a key, kill processes, restart cluster, and verify persistent key exists.
This test is a functional/integration test and may take several seconds.
"""
import subprocess
import time
import re
import urllib.request
import json
import os
import sys

# Ensure repo top-level is importable when running this script directly
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.fault_tests import find_leader, probe_states
import raft_client
import shutil
import datetime

START_TIMEOUT = 10
FIND_LEADER_TIMEOUT = 60
COMMIT_WAIT = 20

ARTIFACTS_DIR = 'artifacts'


def dump_logs(reason: str = 'failure'):
    """Copy node-*.log into artifacts/<timestamp>_<reason>/ for postmortem"""
    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    dest = f"{ARTIFACTS_DIR}/{ts}_{reason}"
    try:
        os.makedirs(dest, exist_ok=True)
        for fname in os.listdir('.'):
            if fname.startswith('node-') and fname.endswith('.log'):
                shutil.copy(fname, os.path.join(dest, fname))
        print(f'Logs dumped to: {dest}')
    except Exception as e:
        print('Failed to dump logs:', e)



def start_cluster_and_get_pids(timeout=20):
    print('Starting cluster... (collecting PIDs)')
    proc = subprocess.Popen([sys.executable, 'start_cluster.py', '--force'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    start = time.time()
    pids = []
    # Read lines until we see 'PIDs:' or timeout
    try:
        while time.time() - start < timeout:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            print('[start_cluster]', line.strip())
            m = re.search(r'PIDs:\s*\[([^\]]+)\]', line)
            if m:
                pid_str = m.group(1)
                pids = [int(x.strip()) for x in pid_str.split(',') if x.strip()]
                break
    finally:
        # close proc stdout but leave child python node processes running
        try:
            proc.kill()
        except Exception:
            pass
    if not pids:
        print('Could not parse PIDs from start_cluster output')
    else:
        print('Started PIDs:', pids)
    return pids


def kill_pids(pids):
    print('Killing PIDs:', pids)
    for pid in pids:
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print('Kill failed for', pid, e)


def wait_for_kv(key, expected_value, timeout=COMMIT_WAIT):
    start = time.time()
    while time.time() - start < timeout:
        states = probe_states()
        for nid, st in states.items():
            if isinstance(st, dict):
                kv = st.get('kv_snapshot', {})
                if kv.get(key) == expected_value:
                    return True
        time.sleep(0.3)
    return False


def run_durability_test():
    # NOTE: We do not forcibly kill all Python processes here to avoid terminating the test runner.
    # Ensure manually that no conflicting cluster is running before running this test.
    print('Proceeding to start cluster (ensure no other cluster is running)')
    time.sleep(0.5)

    pids = start_cluster_and_get_pids()
    if not pids:
        print('Cluster did not start')
        dump_logs('cluster_start_failed')
        return False

    # find leader
    print('Finding leader...')
    leader, leader_addr = find_leader(timeout=FIND_LEADER_TIMEOUT)
    if not leader:
        print('No leader found')
        dump_logs('no_leader_found')
        return False
    print('Leader found:', leader)

    # Wait for stability: ensure leader reports role==LEADER and majority agree on leader_id
    def wait_for_stable_leader(leader_id, timeout=10.0):
        start = time.time()
        while time.time() - start < timeout:
            states = probe_states()
            leader_reports = 0
            leader_state = None
            for nid, st in states.items():
                if isinstance(st, dict):
                    if st.get('leader_id') == leader_id:
                        leader_reports += 1
                    if int(nid) == int(leader_id):
                        leader_state = st
            # Require: leader node reports role==LEADER and a majority report the same leader_id
            # Also prefer that leader has at least one committed entry (noop) to assert leadership
            if leader_state and leader_state.get('role') == 'LEADER' and leader_reports >= (len(states) // 2) + 1:
                # check for a committed noop or commit_index >= 0
                if leader_state.get('committed_command') is not None or leader_state.get('commit_index', -1) >= 0:
                    return True
            time.sleep(0.25)
        return False

    if not wait_for_stable_leader(leader, timeout=5.0):
        print('Leader not stable after wait; trying to rediscover leader')
        leader, leader_addr = find_leader(timeout=FIND_LEADER_TIMEOUT)
        if not leader:
            print('No leader found on rediscovery')
            return False
        print('Leader rediscovered:', leader)

    # send command (keep retrying until cluster accepts or timeout)
    print('Sending persistent command to leader (will retry)')
    start = time.time()
    ok = False
    overall_timeout = 60.0  # allow more time for leader stability and replication
    while time.time() - start < overall_timeout:
        # Retry more aggressively to handle transient leader instability
        ok = raft_client.send_command('set dur_key 42', max_attempts=12, backoff=0.5)
        if ok:
            break
        time.sleep(1.0)
    if not ok:
        print('Client failed to commit command after repeated attempts (extended retries)')
        print('Snapshot before restart:', probe_states())
        # Check if the key is nevertheless present in any node state; if so, proceed (best-effort)
        if wait_for_kv('dur_key', '42', timeout=5):
            print('Key observed in cluster despite client errors; proceeding to restart to verify persistence')
        else:
            dump_logs('client_commit_failed')
            return False

    # wait for commit and KV reflect
    if not wait_for_kv('dur_key', '42', timeout=COMMIT_WAIT):
        print('Key not observed in cluster before restart')
        print('Snapshot:', probe_states())
        return False

    print('Key committed; now killing cluster to test persistence')
    kill_pids(pids)
    time.sleep(2)

    # restart cluster
    pids2 = start_cluster_and_get_pids()
    if not pids2:
        print('Cluster did not restart')
        dump_logs('cluster_restart_failed')
        return False

    # wait for leader and check kv
    leader2, leader2_addr = find_leader(timeout=FIND_LEADER_TIMEOUT)
    if not leader2:
        print('No leader after restart')
        dump_logs('no_leader_after_restart')
        return False
    print('Leader after restart:', leader2)

    if not wait_for_kv('dur_key', '42', timeout=COMMIT_WAIT):
        print('Key not found after restart')
        print('Snapshot:', probe_states())
        dump_logs('key_missing_after_restart')
        return False

    print('Durability test: PASS')
    return True


def test_durability():
    # Run the durability scenario as part of pytest so CI will execute it.
    assert run_durability_test()


if __name__ == '__main__':
    ok = run_durability_test()
    print('Result:', ok)
    import sys
    sys.exit(0 if ok else 1)
