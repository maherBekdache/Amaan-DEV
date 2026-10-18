from __future__ import annotations

import asyncio
import time
from enum import Enum

from pydantic import BaseModel


class SourceStatus(str, Enum):
    ok = "ok"
    not_configured = "not_configured"  # no API key / disabled
    timeout = "timeout"
    rate_limited = "rate_limited"
    error = "error"


class SourceVerdict(str, Enum):
    malicious = "malicious"
    suspicious = "suspicious"
    clean = "clean"  # checked, nothing found
    unknown = "unknown"  # the source has no data about this link


class SourceResult(BaseModel):
    source: str  # display name, e.g. "VirusTotal"
    kind: str  # "blocklist" | "engines" | "sandbox"
    status: SourceStatus
    verdict: SourceVerdict = SourceVerdict.unknown
    detail: str = ""
    community: bool = False  # the evidence comes from people's reports (vs. automated engines)


class RateLimiter:
    """At most `n` calls per `per` seconds (free API tiers)."""

    def __init__(self, n: int, per: float) -> None:
        self.n, self.per = n, per
        self.calls: list[float] = []
        self.lock = asyncio.Lock()

    async def acquire(self, max_wait: float) -> bool:
        async with self.lock:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < self.per]
            if len(self.calls) >= self.n:
                wait = self.per - (now - self.calls[0])
                if wait > max_wait:
                    return False
                await asyncio.sleep(wait)
            self.calls.append(time.monotonic())
            return True


class TTLCache:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.data: dict[str, tuple[float, SourceResult]] = {}

    def get(self, key: str) -> SourceResult | None:
        hit = self.data.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        return None

    def put(self, key: str, value: SourceResult) -> None:
        if len(self.data) > 5000:
            self.data.clear()
        self.data[key] = (time.monotonic(), value)
