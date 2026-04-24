"""Local lightweight cachetools compatibility shim for TTLCache."""

from __future__ import annotations

import time


class TTLCache(dict):
    def __init__(self, maxsize: int, ttl: int):
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._expiry: dict[object, float] = {}

    def _prune(self) -> None:
        now = time.time()
        expired = [key for key, exp in self._expiry.items() if exp <= now]
        for key in expired:
            self._expiry.pop(key, None)
            super().pop(key, None)
        while len(self) > self.maxsize:
            oldest_key = min(self._expiry, key=self._expiry.get)
            self._expiry.pop(oldest_key, None)
            super().pop(oldest_key, None)

    def __contains__(self, key: object) -> bool:
        self._prune()
        return super().__contains__(key)

    def __getitem__(self, key):
        self._prune()
        return super().__getitem__(key)

    def __setitem__(self, key, value) -> None:
        self._prune()
        super().__setitem__(key, value)
        self._expiry[key] = time.time() + self.ttl

