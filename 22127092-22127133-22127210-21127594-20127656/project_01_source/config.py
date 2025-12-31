# ================================
# Global configuration for RAFT (Stable)
# ================================

import random

# -------------------------------------------------
# NODE CONFIG
# -------------------------------------------------
# ⚠️ NODE_ID KHÔNG ĐƯỢC hard-code
# Giá trị này sẽ được gán lại trong run_node.py
NODE_ID = None

# -------------------------------------------------
# CLUSTER CONFIG
# -------------------------------------------------

# Mapping node_id -> gRPC address
NODES = {
    1: "127.0.0.1:5001",
    2: "127.0.0.1:5002",
    3: "127.0.0.1:5003",
    4: "127.0.0.1:5004",
    5: "127.0.0.1:5005",
}

# Danh sách node ID
ALL_NODES = list(NODES.keys())

# Tổng số node trong cluster
NUM_NODES = len(NODES)

# Majority quorum
# Ví dụ: 5 node -> majority = 3
MAJORITY = (NUM_NODES // 2) + 1

# -------------------------------------------------
# RAFT TIMING CONSTANTS (SECONDS)
# -------------------------------------------------
# Election timeout nên cao hơn heartbeat để tránh liên tục thay leader
# Mildly increase election timeouts to reduce split-vote churn on loaded systems
ELECTION_TIMEOUT_MIN = 2.5  # giây (was 2.0)
ELECTION_TIMEOUT_MAX = 5.0  # giây (was 4.0)

# Slightly relax heartbeat frequency to reduce gRPC contention on shared machines
HEARTBEAT_INTERVAL = 0.3  # giây (was 0.2)

# -------------------------------------------------
# RAFT STATES
# -------------------------------------------------
FOLLOWER = "FOLLOWER"
CANDIDATE = "CANDIDATE"
LEADER = "LEADER"

# -------------------------------------------------
# UTILITY FUNCTIONS
# -------------------------------------------------
def random_election_timeout():
    """
    Sinh election timeout ngẫu nhiên (giây)
    Giúp tránh nhiều node cùng lúc trở thành candidate
    """
    return random.uniform(
        ELECTION_TIMEOUT_MIN,
        ELECTION_TIMEOUT_MAX
    )
