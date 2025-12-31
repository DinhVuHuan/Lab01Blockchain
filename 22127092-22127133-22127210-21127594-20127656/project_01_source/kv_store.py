"""
Simple file-backed key-value store for durability tests.
Implements atomic writes via temp file + rename.
"""
import json
import os
from typing import Optional

class KVStore:
    def __init__(self, path: str):
        self.path = path
        self._data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception:
                # If corrupt, start fresh but keep file for manual inspection
                self._data = {}
        else:
            self._data = {}

    def _persist(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str):
        self._data[key] = value
        self._persist()

    def keys(self):
        return list(self._data.keys())

    def to_dict(self):
        return dict(self._data)
