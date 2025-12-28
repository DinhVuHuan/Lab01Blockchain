import subprocess
import time
import os

import sys
PY = os.environ.get('PYTHON', sys.executable)

# Pre-flight: ensure required ports are free (can be bypassed with --force or FORCE_CLUSTER env var)
FORCE = '--force' in sys.argv or os.environ.get('FORCE_CLUSTER') == '1'
if not FORCE:
    try:
        cp = subprocess.run([PY, 'tools/check_ports.py'], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(cp.stdout)
    except subprocess.CalledProcessError as ex:
        print('Port preflight failed:')
        print(ex.stdout)
        print('Use --force or set FORCE_CLUSTER=1 to override and continue (only for local debugging).')
        print('Aborting cluster start to avoid interfering with existing processes.')
        sys.exit(1)
else:
    print('FORCE flag set; skipping port preflight. Proceeding to start cluster (local debug mode).')

procs = []
# Reduce gRPC noise from child processes (some platforms print address-resolution warnings)
env = os.environ.copy()
env['GRPC_VERBOSITY'] = 'error'
for i in range(1,6):
    print(f"Starting node {i}")
    p = subprocess.Popen([PY, '-u', 'start_node.py', str(i)], env=env)
    procs.append(p)
    time.sleep(0.5)
# Always print started PIDs quickly so callers can inspect process ids even if startup later fails
pids_list = [p.pid for p in procs]
print('Started PIDs (initial):', pids_list)
# Also print a simple PIDs: line so external parsers can reliably extract PIDs
print('PIDs:', pids_list)
# Quick sanity check: wait a short moment and detect any child processes that exited immediately
time.sleep(1)
for idx, p in enumerate(procs, start=1):
    rc = p.poll()
    if rc is not None:
        print(f'PID {p.pid} (node {idx}) exited immediately with code {rc}')
        # print tail of node log for quick diagnostics (if available)
        try:
            logf = f'node-{idx}.log'
            if os.path.exists(logf):
                with open(logf, 'rb') as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    tail_size = min(8192, size)
                    fh.seek(size - tail_size)
                    tail = fh.read().decode(errors='replace')
                print(f'--- tail of {logf} (last {tail_size} bytes) ---')
                print(tail)
                print('--- end tail ---')
        except Exception as e:
            # Print a safe, ASCII-friendly representation of the exception to avoid encoding errors
            print('Failed to read node log for quick diagnostics: (exception repr follows)')
            print(repr(e))

# Wait for status endpoints to become available
import urllib.request, json
start = time.time()
ready = False
while time.time() - start < 20:
    ok_count = 0
    for i in range(1, 6):
        url = f"http://127.0.0.1:{5000 + i + 1000}/state"
        try:
            with urllib.request.urlopen(url, timeout=0.5) as r:
                data = json.loads(r.read().decode())
                ok_count += 1
        except Exception:
            pass
    if ok_count >= 3:
        ready = True
        break
    time.sleep(0.5)

if not ready:
    print('Warning: not enough nodes responded to /state within timeout; cluster did not become healthy')
    # Do not claim success; exit with non-zero so callers detect failure
    print('Cluster failed to start correctly; aborting')
    print('Started PIDs (may have exited):', [p.pid for p in procs])
    # Print each PID status to help debugging which process exited early
    for p in procs:
        rc = p.poll()
        status = 'running' if rc is None else f'exited(code={rc})'
        print(f'PID {p.pid} status: {status}')
    sys.exit(2)
else:
    print('Cluster status endpoints healthy')

# Wait for an elected leader to stabilize (role==LEADER on leader node and majority agrees)
print('Waiting for leader stability...')
from tools.fault_tests import find_leader, probe_states
import config
start = time.time()
leader_ok = False
while time.time() - start < 15:
    lid, laddr = find_leader(timeout=2, probe_timeout=0.5)
    if not lid:
        time.sleep(0.5)
        continue
    states = probe_states()
    leader_reports = 0
    leader_state = None
    for nid, st in states.items():
        if isinstance(st, dict):
            if st.get('leader_id') == lid:
                leader_reports += 1
            if int(nid) == int(lid):
                leader_state = st
    if leader_state and leader_state.get('role') == 'LEADER' and leader_reports >= config.MAJORITY:
        leader_ok = True
        print(f'Leader {lid} is stable (reported by {leader_reports} nodes)')
        break
    time.sleep(0.5)

if not leader_ok:
    print('Warning: no stable leader detected within timeout; cluster may be unstable')

print('All nodes started. PIDs:', [p.pid for p in procs])

print('Sleeping 4s to warm up...')
time.sleep(4)
print('Done. Use taskkill /F /IM python.exe to stop all (or kill PIDs individually)')