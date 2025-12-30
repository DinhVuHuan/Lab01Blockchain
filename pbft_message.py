from typing import Any


# PBFT Message Types
PRE_PREPARE: str = "PRE_PREPARE"
PREPARE: str = "PREPARE"
COMMIT: str = "COMMIT"


class PBFTMessage:
    """Lightweight PBFT protocol message wrapper."""

    def __init__(self, msg_type: str, block: Any, sender: int) -> None:
        self.type: str = msg_type
        self.block: Any = block
        self.sender: int = sender

    def __repr__(self) -> str:
        return f"PBFTMessage(type={self.type}, height={getattr(self.block, 'height', '?')}, sender={self.sender})"