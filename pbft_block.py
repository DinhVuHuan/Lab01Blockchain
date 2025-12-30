import hashlib
from typing import Any


class Block:
    """Minimal immutable block for PBFT durability tests."""

    def __init__(self, height: int, prev_hash: str) -> None:
        self.height: int = height
        self.prev_hash: str = prev_hash
        self.hash: str = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = f"{self.height}{self.prev_hash}".encode()
        return hashlib.sha256(payload).hexdigest()

    def __repr__(self) -> str:
        return f"Block(height={self.height}, hash={self.hash[:6]})"