import subprocess
import time
import os
import config

PY = os.environ.get('PYTHON', 'python')
procs = []
for i in range(1,6):
    print(f"Starting node {i}")
    p = subprocess.Popen([PY, '-u', 'start_node.py', str(i)])
    procs.append(p)
    # wait long enough for first node to stabilize
    time.sleep(int(config.ELECTION_TIMEOUT_MIN * 1.2))

print('All nodes started staggered. PIDs:', [p.pid for p in procs])
print('Done.')