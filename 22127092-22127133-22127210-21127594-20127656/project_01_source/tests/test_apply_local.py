"""
Lightweight test to verify apply_committed_loop applies committed entries to KV store for a single node.
"""
import time
import os
import json
import sys
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import config
from raft_node import RaftNode
from raft_state import LogEntry


def run_test():
    # use a dedicated node id to avoid interfering with cluster
    config.NODE_ID = 99
    config.NODES[99] = '127.0.0.1:5999'

    node = RaftNode()
    # make node leader and append an entry
    node.state.role = config.LEADER
    node.state.current_term = 1
    with node.state.lock:
        node.state.log.append(LogEntry(1, 'set local_key local_val'))
        idx = len(node.state.log) - 1
        node.state.commit_index = idx

    # wait briefly for apply loop to run
    time.sleep(0.5)

    # check kv_store file
    data_path = os.path.join('data', f'node_{node.node_id}.json')
    if not os.path.exists(data_path):
        print('KV file not found:', data_path)
        node.running = False
        return False
    with open(data_path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    node.running = False
    if d.get('local_key') == 'local_val':
        print('apply local test: PASS')
        return True
    else:
        print('apply local test: FAIL', d)
        return False

if __name__ == '__main__':
    print(run_test())
