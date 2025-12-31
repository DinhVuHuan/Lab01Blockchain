from collections import defaultdict
from typing import Any, List, Set

from pbft_message import PRE_PREPARE, PREPARE, COMMIT, PBFTMessage


class PBFTNode:
    """PBFT protocol node (supports primary, byzantine, and durability tests)."""

    def __init__(
        self, node_id: int, total_nodes: int, is_primary: bool = False, byzantine: bool = False
    ) -> None:
        self.node_id = node_id
        self.is_primary = is_primary
        self.byzantine = byzantine

        # Tối đa f Byzantine chịu được
        self.f = (total_nodes - 1) // 3

        self.peers = []
        self.prepare_votes = defaultdict(set)
        self.commit_votes = defaultdict(set)

        self.sent_commit = set()
        self.committed_blocks = set()
        self.finalized_blocks = set() 
        self.blacklist = set()
        self.pre_prepares_by_height = defaultdict(list)  

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

        if block.hash in self.finalized_blocks:
            print(f"[Primary {self.node_id}] Block already finalized → skip duplicate proposal")
            return

        print(f"[Primary {self.node_id}] PRE-PREPARE {block}")

        # Nếu primary honest → tự vote PREPARE + broadcast
        if not self.byzantine:
            self.prepare_votes[block.hash].add(self.node_id)
            self.broadcast(PBFTMessage(PREPARE, block, self.node_id))

        # Primary Byzantine thì chỉ broadcast PRE-PREPARE xấu/đúng tùy test
        self.broadcast(PBFTMessage(PRE_PREPARE, block, self.node_id))


    def receive(self, msg: PBFTMessage) -> None:
        # Bỏ qua message từ node đã bị blacklist
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
        h = block.hash
        ht = block.height

        # Lưu history primary proposals theo height
        self.pre_prepares_by_height[ht].append((msg.sender, h))

        # Detect equivocation: lấy tất cả hash do PRIMARY (1) gửi ở height này
        primary_hashes = {hash_val for sender, hash_val in self.pre_prepares_by_height[ht] if sender == 1}

        if len(primary_hashes) > 1:
            print(f"[Node {self.node_id}] Primary equivocation at height {ht} → blacklist {msg.sender}")
            self.blacklist.add(msg.sender)
            return

        print(f"[Node {self.node_id}] → PREPARE {block}")
        self.prepare_votes[h].add(self.node_id)
        self.broadcast(PBFTMessage(PREPARE, block, self.node_id))


    def _on_prepare(self, msg: PBFTMessage) -> None:
        if self.byzantine:
            return

        block = msg.block
        h = block.hash
        ht = block.height

        if h in self.finalized_blocks:
            print(f"[Node {self.node_id}] Block already finalized → ignore PREPARE")
            return

        # Kiểm tra hash có khớp với proposal của PRIMARY ở height này không
        for sender, prev_hash in self.pre_prepares_by_height[ht]:
            if sender == 1 and prev_hash != h:
                print(f"[Node {self.node_id}] PREPARE hash mismatch with primary PRE-PREPARE → ignore")
                return

        self.prepare_votes[h].add(msg.sender)

        # Nếu đủ quorum PREPARE → gửi COMMIT
        if len(self.prepare_votes[h]) >= 3 and h not in self.sent_commit:
            self.sent_commit.add(h)
            self.commit_votes[h].add(self.node_id)
            self.broadcast(PBFTMessage(COMMIT, block, self.node_id))
            self._check_commit_quorum(block)


    def _on_commit(self, msg: PBFTMessage) -> None:
        if self.byzantine:
            return

        block = msg.block
        h = block.hash
        ht = block.height

        # Bỏ qua COMMIT nếu chưa từng PREPARE hoặc hash không khớp primary
        if h not in self.prepare_votes:
            print(f"[Node {self.node_id}] COMMIT arrived early or unknown block → ignore")
            return

        for sender, prev_hash in self.pre_prepares_by_height[ht]:
            if sender == 1 and prev_hash != h:
                print(f"[Node {self.node_id}] COMMIT hash mismatch with primary PRE-PREPARE → ignore")
                return

        self.commit_votes[h].add(msg.sender)
        self._check_commit_quorum(block)


    def _check_commit_quorum(self, block: Any) -> None:
        h = block.hash
        ht = block.height

        if h in self.finalized_blocks:
            return

        # Chỉ finalize khi đủ 3 COMMIT hợp lệ từ nodes khác nhau
        if len(self.commit_votes[h]) >= 3:
            self.finalized_blocks.add(h)
            self.committed_blocks.add(h)
            self.blacklist.update(
                sender for sender in self.commit_votes[h] if sender not in self.prepare_votes[h]
            )
            print(f"[Node {self.node_id}] FINALIZED {block}")
