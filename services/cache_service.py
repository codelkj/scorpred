from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
from typing import Any

from cachetools import TTLCache

_logger = logging.getLogger(__name__)

_local_cache = TTLCache(maxsize=2000, ttl=3600)
_redis_client = None


class _LazyModuleProxy:
    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


redis = _LazyModuleProxy("redis")


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return None
    try:
        _redis_client = redis.from_url(redis_url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        _redis_client.ping()
        return _redis_client
    except Exception as exc:
        _logger.warning("Redis unavailable, using local cache fallback: %s", exc)
        _redis_client = None
        return None


def make_key(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"scorpred:{digest}"


def get_json(key: str) -> Any:
    client = _get_redis_client()
    if client is not None:
        try:
            value = client.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception as exc:
            _logger.warning("Redis get failed key=%s: %s", key, exc)
    value = _local_cache.get(key)
    if value is None:
        return None
    return value


def set_json(key: str, value: Any, ttl: int) -> None:
    if value is None:
        return
    client = _get_redis_client()
    if client is not None:
        try:
            client.setex(key, ttl, json.dumps(value))
            return
        except Exception as exc:
            _logger.warning("Redis set failed key=%s: %s", key, exc)
    _local_cache[key] = value


def delete(key: str) -> None:
    client = _get_redis_client()
    if client is not None:
        try:
            client.delete(key)
        except Exception as exc:
            _logger.warning("Redis delete failed key=%s: %s", key, exc)
    _local_cache.pop(key, None)
