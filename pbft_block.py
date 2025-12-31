import hashlib
from typing import Any


class Block:
    """Minimal immutable block for PBFT durability tests."""

    def __init__(self, height: int, prev_hash: str, override_hash=None) -> None:
        self.height: int = height
        self.prev_hash: str = prev_hash
        self.hash = override_hash if override_hash else self.compute_hash()

    def compute_hash(self) -> str:
        payload = f"{self.height}{self.prev_hash}".encode()
        return hashlib.sha256(payload).hexdigest()

    def __repr__(self) -> str:
        return f"Block(height={self.height}, hash={self.hash[:6]})"