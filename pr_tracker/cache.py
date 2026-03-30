"""Disk-persisted ETag cache for GitHub API responses.

Mirrors the pattern from ComfyUI-Launcher/src/main/lib/fetch.ts:
- Store {etag, data} per URL in a JSON file
- Send If-None-Match on requests; 304 = free (no rate-limit cost)
- Fall back to cached data on errors
- LRU eviction when cache exceeds MAX_SIZE
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

MAX_SIZE = 200
CACHE_FILE = Path(__file__).resolve().parent / ".cache" / "etag-cache.json"


class ETagCache:
    def __init__(self) -> None:
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for url, entry in raw.items():
                    if (
                        isinstance(entry, dict)
                        and isinstance(entry.get("etag"), str)
                        and "data" in entry
                    ):
                        self._cache[url] = entry
        except (OSError, json.JSONDecodeError):
            pass

    def _persist(self) -> None:
        try:
            from safe_file import atomic_write
            atomic_write(
                CACHE_FILE,
                json.dumps(dict(self._cache), separators=(",", ":")) + "\n",
            )
        except OSError:
            pass

    def get(self, url: str) -> dict | None:
        self._ensure_loaded()
        entry = self._cache.get(url)
        if entry is not None:
            self._cache.move_to_end(url)
        return entry

    def set(self, url: str, etag: str, data: object) -> None:
        self._ensure_loaded()
        self._cache.pop(url, None)
        self._cache[url] = {"etag": etag, "data": data}
        while len(self._cache) > MAX_SIZE:
            self._cache.popitem(last=False)
        self._persist()


# Module-level singleton
cache = ETagCache()
