from pbft_block import Block
from pbft_node import PBFTNode
from pbft_message import PBFTMessage, PRE_PREPARE, PREPARE, COMMIT

# ====== Helper ======
def build_network(byzantine_nodes=None, primary_byzantine=False):
    if byzantine_nodes is None:
        byzantine_nodes = []

    nodes = []
    total = 5
    primary_id = 1

    for i in range(1, total + 1):
        is_primary = (i == primary_id)
        byz = primary_byzantine if is_primary else (i in byzantine_nodes)
        node = PBFTNode(i, total, is_primary, byz)  # fixed constructor
        nodes.append(node)

    for n in nodes:
        n.connect(nodes)

    return nodes

def collect_commits(nodes, block_hash):
    return [n.node_id for n in nodes if block_hash in n.committed_blocks]

# ====== Tests ======
def test_consensus_success():
    nodes = build_network(byzantine_nodes=[3])
    print("\n--- Test A: Consensus thành công trong ngưỡng f ---")
    block = Block(1, "genesis")
    nodes[0].start_pbft(block)

    committed = collect_commits(nodes, block.hash)
    print("Committed nodes:", committed)
    assert len(committed) >= 3  # quorum 3

def test_byzantine_primary_bad_hash():
    nodes = build_network(primary_byzantine=True)
    print("\n--- Test B: Primary Byzantine gửi sai hash ---")
    block = Block(1, "genesis")
    block.hash = "0" * 64  # invalid hash

    primary = nodes[0]
    primary.broadcast(PBFTMessage(PRE_PREPARE, block, primary.node_id))  # primary byz broadcast bad

    # PASS nếu honest không commit sai block
    honest_bad = any(block.hash in n.committed_blocks for n in nodes if not n.byzantine)
    print("Honest nodes commit bad block?", honest_bad)
    assert not honest_bad  # must be True if safe

def test_byzantine_primary_equivocation():
    nodes = build_network(primary_byzantine=True)
    print("\n--- Test C: Primary Byzantine equivocate (2 block cùng height) ---")
    b1 = Block(1, "A")
    b2 = Block(1, "B")

    primary = nodes[0]
    primary.broadcast(PBFTMessage(PRE_PREPARE, b1, primary.node_id))
    primary.broadcast(PBFTMessage(PRE_PREPARE, b2, primary.node_id))

    honest_commit_both = any(
        b1.hash in n.committed_blocks and b2.hash in n.committed_blocks
        for n in nodes if not n.byzantine
    )
    print("Honest commit both blocks?", honest_commit_both)
    assert not honest_commit_both  # safe if not both

def test_byzantine_replica_spam_votes():
    nodes = build_network(byzantine_nodes=[3])
    print("\n--- Test D: Replica Byzantine spam vote sai/duplicate ---")
    block = Block(1, "genesis")
    nodes[0].start_pbft(block)

    byz = nodes[2]
    spam_block = Block(1, "X")
    byz.broadcast(PBFTMessage(COMMIT, spam_block, byz.node_id))
    byz.broadcast(PBFTMessage(COMMIT, spam_block, byz.node_id))

    bad_commits = collect_commits(nodes, spam_block.hash)
    print("Bad commits on honest?", bad_commits)
    assert len(bad_commits) == 0

def test_unexpected_message_order():
    nodes = build_network(byzantine_nodes=[3])
    print("\n--- Test E: Message sai thứ tự / message lạ ---")
    block = Block(1, "genesis")

    nodes[1].receive(PBFTMessage(COMMIT, block, 2))
    nodes[2].receive(PBFTMessage("RANDOM", block, 3))
    nodes[3].receive(PBFTMessage(PREPARE, block, 4))

    commits = collect_commits(nodes, block.hash)
    print("Commits on honest?", commits)
    assert len(commits) == 0

def test_fault_limit_exceeded():
    nodes = build_network(byzantine_nodes=[3, 4])
    print("\n--- Test F: Byzantine vượt quá f, honest phải an toàn ---")
    block = Block(1, "genesis")
    nodes[0].start_pbft(block)

    honest_commit = any(block.hash in n.committed_blocks for n in nodes if not n.byzantine)
    print("Honest commit khi quá f?", honest_commit)
    assert not honest_commit  # PASS nếu honest KHÔNG commit (liveness có thể mất nhưng safety giữ)

def test_persistency_no_duplicate_commit():
    nodes = build_network(byzantine_nodes=[3])
    print("\n--- Test G: Durability – không finalize trùng ---")
    block = Block(1, "genesis")
    nodes[0].start_pbft(block)
    nodes[0].start_pbft(block)  # duplicate proposal

    commits = collect_commits(nodes, block.hash)
    print("Commits:", commits)
    assert len(commits) >= 3  # consensus vẫn xảy ra nhưng không duplicate logic

# ====== Run ======
def run_all_tests():
    results = {}
    results['A'] = test_consensus_success()
    results['B'] = test_byzantine_primary_bad_hash()
    results['C'] = test_byzantine_primary_equivocation()
    results['D'] = test_byzantine_replica_spam_votes()
    results['E'] = test_unexpected_message_order()
    results['F'] = test_fault_limit_exceeded()
    results['G'] = test_persistency_no_duplicate_commit()

    print("\n=== PBFT TEST SUMMARY ===")
    for k, v in results.items():
        print(f"Test {k}: {'PASS' if v else 'FAIL'}")
    print("========================")

if __name__ == '__main__':
    run_all_tests()
