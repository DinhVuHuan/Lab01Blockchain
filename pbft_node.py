# pbft_node.py
from collections import defaultdict
from pbft_message import PRE_PREPARE, PREPARE, COMMIT, PBFTMessage

class PBFTNode:
    def __init__(self, node_id, total_nodes, is_primary=False, byzantine=False):
        self.node_id = node_id
        self.is_primary = is_primary
        self.byzantine = byzantine

        self.f = (total_nodes - 1) // 3
        self.peers = []

        # Lưu trữ votes
        self.prepare_votes = defaultdict(set)
        self.commit_votes = defaultdict(set)
        
        # Quản lý trạng thái để tránh gửi lặp lại
        self.sent_commit = set()   # Các block hash mà node này đã gửi COMMIT message
        self.committed_blocks = set() # Các block hash đã finalize

        self.blacklist = set()

    def connect(self, peers):
        self.peers = peers

    # ===== NETWORK =====
    def broadcast(self, msg):
        # Giả lập mạng: gửi tuần tự cho các peer
        for p in self.peers:
            if p.node_id != self.node_id: # Không gửi ngược lại cho chính mình qua mạng (xử lý nội bộ)
                p.receive(msg)

    # ===== PROTOCOL =====
    def start_pbft(self, block):
        if not self.is_primary:
            return
        print(f"[Primary {self.node_id}] PRE-PREPARE {block}")

        # Primary tự vote PREPARE cho chính mình
        self.prepare_votes[block.hash].add(self.node_id)

        msg = PBFTMessage(PRE_PREPARE, block, self.node_id)
        self.broadcast(msg)

    def receive(self, msg):
        if msg.sender in self.blacklist:
            return

        if msg.type == PRE_PREPARE:
            self.on_pre_prepare(msg)
        elif msg.type == PREPARE:
            self.on_prepare(msg)
        elif msg.type == COMMIT:
            self.on_commit(msg)

    # ===== PHASES =====
    def on_pre_prepare(self, msg):
        if self.byzantine:
            print(f"[Node {self.node_id}] Byzantine ignore PRE-PREPARE")
            return

        print(f"[Node {self.node_id}] PREPARE {msg.block}")
        
        # 1. Vote cho chính mình trước
        self.prepare_votes[msg.block.hash].add(self.node_id)
        
        # 2. Broadcast PREPARE message
        prepare = PBFTMessage(PREPARE, msg.block, self.node_id)
        self.broadcast(prepare)

        # Kiểm tra ngay (trường hợp mạng nhỏ hoặc logic đặc biệt), 
        # nhưng thường Pre-prepare xong chưa đủ vote ngay để commit đâu.
        self.check_prepare_threshold(msg.block)

    def on_prepare(self, msg):
        h = msg.block.hash

        # Mô phỏng Byzantine: Gửi thông tin sai lệch hoặc im lặng
        if self.byzantine:
            # Ở đây Byzantine node có thể gửi vote sai hash, 
            # node trung thực sẽ lưu vào key khác trong defaultdict -> không ảnh hưởng key đúng.
            return 

        self.prepare_votes[h].add(msg.sender)
        self.check_prepare_threshold(msg.block)

    def check_prepare_threshold(self, block):
        h = block.hash
        # Điều kiện: 2f + 1 phiếu PREPARE
        if len(self.prepare_votes[h]) >= 2 * self.f + 1:
            # QUAN TRỌNG: Kiểm tra xem đã gửi COMMIT cho block này chưa?
            if h not in self.sent_commit:
                # Đánh dấu đã gửi để không spam
                self.sent_commit.add(h)
                
                # 1. Tự vote COMMIT cho chính mình
                self.commit_votes[h].add(self.node_id)
                
                # 2. Broadcast COMMIT message
                commit_msg = PBFTMessage(COMMIT, block, self.node_id)
                self.broadcast(commit_msg)

                # 3. Kiểm tra luôn xem đủ điều kiện commit chưa (phòng trường hợp mạng rất nhanh/nhỏ)
                self.check_commit_threshold(block)

    def on_commit(self, msg):
        h = msg.block.hash
        
        # Node chỉ xử lý commit nếu nó đã biết về block này (đã prepare)
        if h not in self.prepare_votes:
            return

        self.commit_votes[h].add(msg.sender)
        self.check_commit_threshold(msg.block)

    def check_commit_threshold(self, block):
        h = block.hash
        # Điều kiện: 2f + 1 phiếu COMMIT
        if len(self.commit_votes[h]) >= 2 * self.f + 1:
            if h not in self.committed_blocks:
                self.committed_blocks.add(h)
                print(f"[Node {self.node_id}] ✅ COMMIT {block}")