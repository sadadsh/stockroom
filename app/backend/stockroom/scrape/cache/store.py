"""A URL-keyed TTL response cache (spec sections 3, 4). A fresh hit returns the
stored Page instantly, so repeats never touch the network: this is most of "no
wait times" and "no bans". One JSON file per URL (sha256 of the URL as the
filename), body base64-encoded so arbitrary bytes round-trip. An expired or
unreadable entry is removed and reported as a miss, never surfaced as bad data."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from stockroom.scrape.model import Page


class ResponseCache:
    def __init__(self, root: Path, ttl: float = 86400.0, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.ttl = ttl
        self._clock = clock
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"

    def get(self, url: str) -> Page | None:
        path = self._path(url)
        if not path.exists():
            return None
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            stamp = float(d["stamp"])
            content = base64.b64decode(d["content_b64"])
        except (ValueError, KeyError, OSError):
            path.unlink(missing_ok=True)
            return None
        if self._clock() - stamp >= self.ttl:
            path.unlink(missing_ok=True)
            return None
        return Page(
            url=d["url"],
            final_url=d["final_url"],
            status=int(d["status"]),
            content=content,
            text=d["text"],
            content_type=d["content_type"],
            headers=dict(d.get("headers", {})),
            from_cache=True,
            render_tier="cache",
        )

    def put(self, page: Page) -> None:
        d = {
            "url": page.url,
            "final_url": page.final_url,
            "status": page.status,
            "content_b64": base64.b64encode(page.content).decode("ascii"),
            "text": page.text,
            "content_type": page.content_type,
            "headers": page.headers,
            "stamp": self._clock(),
        }
        self._path(page.url).write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8"
        )

    # -- negative cache (anti-ban, spec section 6) ---------------------------------
    # A freshly-blocked URL is remembered for a SHORT ttl so the engine does not re-hit it
    # (and re-provoke the WAF) on the very next attempt; the short ttl means a later attempt
    # still retries clean once the block has likely lifted.

    def _neg_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.root / f"{key}.neg.json"

    def put_negative(self, url: str, ttl: float = 300.0) -> None:
        self._neg_path(url).write_text(
            json.dumps({"stamp": self._clock(), "ttl": ttl}), encoding="utf-8"
        )

    def is_negative(self, url: str) -> bool:
        path = self._neg_path(url)
        if not path.exists():
            return False
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            stamp = float(d["stamp"])
            ttl = float(d.get("ttl", 300.0))
        except (ValueError, KeyError, OSError):
            path.unlink(missing_ok=True)
            return False
        if self._clock() - stamp >= ttl:
            path.unlink(missing_ok=True)
            return False
        return True
