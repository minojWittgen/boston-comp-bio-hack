"""Content-addressed JSON cache on a directory (a Modal Volume in production).

Only "ok" and "not_found" are cached. Errors are never cached so they retry next run.
Bump CACHE_VERSION when a fetcher's output shape changes, to invalidate old entries.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

# v2: HPA fetchers now return not_found for identifier-only rows and carry
# has_* availability flags; bump invalidates pre-fix entries so they are re-fetched.
CACHE_VERSION = "v2"
CACHEABLE = {"ok", "not_found"}


class JsonCache:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def _path(self, source: str, query: dict) -> Path:
        key = json.dumps({"s": source, "q": query, "v": CACHE_VERSION}, sort_keys=True)
        h = hashlib.sha256(key.encode()).hexdigest()
        return self.root / "cache" / source / h[:2] / f"{h}.json"

    def get(self, source: str, query: dict) -> dict | None:
        p = self._path(source, query)
        if p.exists():
            out = json.loads(p.read_text())
            out["cache_hit"] = True
            return out
        return None

    def put(self, source: str, query: dict, value: dict) -> None:
        if value.get("status") not in CACHEABLE:
            return
        p = self._path(source, query)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value))
        os.replace(tmp, p)  # atomic on the same filesystem

    def fetch(self, source: str, query: dict, fn: Callable[[], dict]) -> dict:
        hit = self.get(source, query)
        if hit is not None:
            return hit
        value = fn()
        value["cache_hit"] = False
        self.put(source, query, value)
        return value
