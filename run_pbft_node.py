from pbft_node import PBFTNode
from pbft_block import Block
 
def run():
    N = 5
    nodes = []

    for i in range(N):
        nodes.append(
            PBFTNode(
                node_id=i,
                total_nodes=N,
                is_primary=(i == 0),
                byzantine=(i == 3)  # node 3 gian lận
            )
        )

    for n in nodes:
        n.connect([p for p in nodes if p != n])

    genesis = Block(1, "GENESIS")
    nodes[0].start_pbft(genesis)

if __name__ == "__main__":
    run()
