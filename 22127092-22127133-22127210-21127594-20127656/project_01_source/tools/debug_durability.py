"""Debug helper: start a 5-node cluster, issue a client command, and collect node logs.

Usage: python tools/debug_durability.py

This script is intended to be used locally to reproduce the Errno 22 server-side exception and capture per-node logs (node-<id>.log).
"""
import subprocess
import sys
import os
import time
import signal

PY = os.environ.get('PYTHON', sys.executable)

procs = []
try:
    # start cluster
    for i in range(1, 6):
        print(f"Starting node {i}")
        p = subprocess.Popen([PY, '-u', 'start_node.py', str(i)])
        procs.append(p)
        time.sleep(0.5)

    print('All nodes started. PIDs:', [p.pid for p in procs])
    print('Sleeping 6s to warm up...')
    time.sleep(6)

    # issue a client command
    print('Issuing client command via raft_client...')
    rc = subprocess.call([PY, 'raft_client.py', "'set dur_key 42'"], shell=False)
    print('raft_client exit code:', rc)

    print('Allowing 2s for replication...')
    time.sleep(2)

    # collect node logs
    print('\n=== Node logs ===')
    for i in range(1, 6):
        path = f"node-{i}.log"
        print(f'--- node {i} ({path}) ---')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                data = f.read()
                # print only the last 2000 chars to avoid flooding
                print(data[-2000:])
        else:
            print('(no log file)')

finally:
    print('Stopping cluster...')
    for p in procs:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    print('Cluster stopped.')
