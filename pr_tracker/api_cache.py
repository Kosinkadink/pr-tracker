"""Shared TTL file cache for API clients."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from safe_file import atomic_write


class TTLCache:
    """Simple file-based TTL cache.

    Each entry is stored as a JSON file with a timestamp.
    """

    def __init__(self, cache_dir: Path, ttl: int = 60) -> None:
        self._dir = cache_dir
        self._ttl = ttl

    def _path(self, key: str) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        safe = key.replace("/", "_").replace(":", "_").replace(" ", "_").replace("<", "").replace(">", "")
        return self._dir / f"{safe}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - raw.get("_ts", 0) < self._ttl:
                return raw.get("data")
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def set(self, key: str, data: Any) -> None:
        path = self._path(key)
        try:
            atomic_write(
                path,
                json.dumps({"_ts": time.time(), "data": data}, indent=2) + "\n",
            )
        except OSError:
            pass
