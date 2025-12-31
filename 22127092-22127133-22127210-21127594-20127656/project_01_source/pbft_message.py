from typing import Any


# PBFT Message Types
PRE_PREPARE: str = "PRE_PREPARE"
PREPARE: str = "PREPARE"
COMMIT: str = "COMMIT"


class PBFTMessage:
    """Lightweight PBFT protocol message wrapper."""

    def __init__(self, msg_type: str, block: Any, sender: int) -> None:
        self.type = msg_type
        self.block = block
        self.sender = sender
        self.height = block.height
        self.hash = block.hash

    def __repr__(self) -> str:
        return f"PBFTMessage(type={self.type}, height={getattr(self.block, 'height', '?')}, sender={self.sender})"