# test_state.py
# Test logic RAFT state (KHÔNG gRPC)

import time
from raft_state import RaftState

def main():
    node = RaftState(1)

    print("\n=== INIT STATE ===")
    node.debug_status()

    print("\n=== WAIT FOR ELECTION TIMEOUT ===")
    while True:
        time.sleep(0.5)

        if node.election_timeout_reached():
            print("\n!!! Election timeout reached !!!")
            node.become_candidate()
            node.debug_status()
            break

    print("\n=== SIMULATE LEADER HEARTBEAT ===")
    time.sleep(1)

    success, term = node.on_append_entries(
        term=node.current_term,
        leader_id=999,
        prev_log_index=-1,
        prev_log_term=0,
        entries=[],
        leader_commit=-1
    )

    print(f"Heartbeat accepted: {success}, term={term}")
    node.debug_status()


if __name__ == "__main__":
    main()
