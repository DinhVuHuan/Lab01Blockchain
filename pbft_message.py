# pbft_message.py

PRE_PREPARE = "PRE_PREPARE"
PREPARE = "PREPARE"
COMMIT = "COMMIT"

class PBFTMessage:
    def __init__(self, msg_type, block, sender):
        self.type = msg_type
        self.block = block
        self.sender = sender
