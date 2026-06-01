from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._init()

    def _init(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        self._conn.commit()

    @staticmethod
    def _key(namespace: str, identifier: str) -> str:
        h = hashlib.sha256(f"{namespace}:{identifier}".encode()).hexdigest()
        return h

    # FAIL entries expire after 1 day; PASS/other entries expire after 30 days
    _TTL_FAIL = 86_400
    _TTL_PASS = 86_400 * 30

    def get(self, namespace: str, identifier: str) -> Any | None:
        key = self._key(namespace, identifier)
        row = self._conn.execute(
            "SELECT value, created_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        created_at = row[1]
        # Apply TTL: shorter for failures so stale NOT_FOUND results don't persist
        is_fail = isinstance(value, dict) and value.get("status") in ("FAIL", "fail")
        ttl = self._TTL_FAIL if is_fail else self._TTL_PASS
        if time.time() - created_at > ttl:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return value

    def set(self, namespace: str, identifier: str, value: Any) -> None:
        key = self._key(namespace, identifier)
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


_cache: Cache | None = None


def get_cache(path: Path | None = None) -> Cache:
    global _cache
    if _cache is None:
        from citesentry.config import get_settings
        p = path or get_settings().cache_path
        _cache = Cache(p)
    return _cache


def reset_cache() -> None:
    global _cache
    if _cache is not None:
        _cache.close()
        _cache = None
