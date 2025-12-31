# pbft_block.py
import hashlib

class Block:
    def __init__(self, height, prev_hash):
        self.height = height
        self.prev_hash = prev_hash
        self.hash = self.compute_hash()

    def compute_hash(self):
        s = f"{self.height}{self.prev_hash}"
        return hashlib.sha256(s.encode()).hexdigest()

    def __repr__(self):
        return f"Block(h={self.height}, hash={self.hash[:6]})"
