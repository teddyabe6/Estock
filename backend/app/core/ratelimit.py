"""Request rate limiting for the endpoints an anonymous caller can hit (PRD 20).

Sign-in, password reset and the public storefront are the routes worth
hammering: credential stuffing on the first two, spam on the third.  Each gets
a sliding-window limit keyed by client address (and email, for sign-in, so one
guessed address cannot lock out a whole office behind one NAT).

The window lives in process memory.  That is enough for the single-container
deployment the PRD starts with; a multi-worker deployment should put the same
limits at the reverse proxy or swap :class:`MemoryWindow` for a Redis-backed
one — the interface is the only thing the rest of the code depends on.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from app.core.errors import DomainError


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"


class MemoryWindow:
    """Sliding-window hit counter, safe to share between request threads."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int, now: float | None = None) -> bool:
        """Record a hit and return whether the caller is still within the limit."""
        now = time.monotonic() if now is None else now
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            # Keep the map from growing with every address that ever called.
            if len(self._hits) > 10_000:
                stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
                for k in stale:
                    del self._hits[k]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RateLimiter:
    """One named limit, e.g. ``RateLimiter("login", limit=10, window_seconds=300)``."""

    def __init__(self, name: str, *, limit: int, window_seconds: int, window: MemoryWindow | None = None):
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds
        self._window = window or MemoryWindow()

    def check(self, *parts: str | None) -> None:
        """Raise :class:`RateLimited` once the caller exceeds the limit."""
        if self.limit <= 0:
            return
        key = f"{self.name}:" + ":".join(p or "-" for p in parts)
        if not self._window.hit(key, limit=self.limit, window_seconds=self.window_seconds):
            minutes = max(1, self.window_seconds // 60)
            raise RateLimited(
                f"Too many attempts. Please wait {minutes} minute(s) and try again.",
                details={"retry_after_seconds": self.window_seconds},
            )

    def reset(self) -> None:
        self._window.reset()
