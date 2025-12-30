from collections import defaultdict
from typing import Any, List, Set

from pbft_message import PRE_PREPARE, PREPARE, COMMIT, PBFTMessage


class PBFTNode:
    """PBFT protocol node (supports primary, byzantine, and durability tests)."""

    def __init__(
        self, node_id: int, total_nodes: int, is_primary: bool = False, byzantine: bool = False
    ) -> None:
        self.node_id: int = node_id
        self.is_primary: bool = is_primary
        self.byzantine: bool = byzantine

        self.f: int = (total_nodes - 1) // 3
        self.peers: List["PBFTNode"] = []

        self.prepare_votes: defaultdict[str, Set[int]] = defaultdict(set)
        self.commit_votes: defaultdict[str, Set[int]] = defaultdict(set)

        self.sent_commit: Set[str] = set()
        self.committed_blocks: Set[str] = set()

        self.finalized_blocks: Set[str] = set()
        self.blacklist: Set[int] = set()

    # ================================
    # Networking
    # ================================

    def connect(self, peers: List["PBFTNode"]) -> None:
        self.peers = peers

    def broadcast(self, msg: PBFTMessage) -> None:
        for peer in self.peers:
            if peer.node_id != self.node_id:
                peer.receive(msg)

    # ================================
    # Protocol Entry
    # ================================

    def start_pbft(self, block: Any) -> None:
        if not self.is_primary:
            return

        print(f"[Primary {self.node_id}] PRE-PREPARE {block}")
        self.prepare_votes[block.hash].add(self.node_id)

        self.broadcast(PBFTMessage(PRE_PREPARE, block, self.node_id))
        self._check_prepare_quorum(block)

    def receive(self, msg: PBFTMessage) -> None:
        if msg.sender in self.blacklist:
            return

        handlers = {
            PRE_PREPARE: self._on_pre_prepare,
            PREPARE: self._on_prepare,
            COMMIT: self._on_commit,
        }

        if msg.type in handlers:
            handlers[msg.type](msg)

    # ================================
    # Phases
    # ================================

    def _on_pre_prepare(self, msg: PBFTMessage) -> None:
        if self.byzantine:
            print(f"[Node {self.node_id}] Byzantine ignore PRE-PREPARE")
            return

        block = msg.block
        print(f"[Node {self.node_id}] PREPARE {block}")

        self.prepare_votes[block.hash].add(self.node_id)
        self.broadcast(PBFTMessage(PREPARE, block, self.node_id))

        self._check_prepare_quorum(block)

    def _on_prepare(self, msg: PBFTMessage) -> None:
        if self.byzantine:
            return

        block = msg.block
        self.prepare_votes[block.hash].add(msg.sender)
        self._check_prepare_quorum(block)

    def _check_prepare_quorum(self, block: Any) -> None:
        h = block.hash
        if len(self.prepare_votes[h]) >= 2 * self.f + 1 and h not in self.sent_commit:
            self.sent_commit.add(h)
            self.commit_votes[h].add(self.node_id)
            self.broadcast(PBFTMessage(COMMIT, block, self.node_id))
            self._check_commit_quorum(block)

    def _on_commit(self, msg: PBFTMessage) -> None:
        block = msg.block
        h = block.hash

        if h not in self.prepare_votes:
            return

        self.commit_votes[h].add(msg.sender)
        self._check_commit_quorum(block)

    def _check_commit_quorum(self, block: Any) -> None:
        h = block.hash
        if len(self.commit_votes[h]) >= 2 * self.f + 1 and h not in self.finalized_blocks:
            self.finalized_blocks.add(h)
            print(f"[Node {self.node_id}] COMMIT {block}")
