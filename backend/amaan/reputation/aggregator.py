"""Runs every reputation source for a link in parallel and caches the answers."""

from __future__ import annotations

import asyncio

import httpx

from amaan.config import Settings
from amaan.reputation import safebrowsing, urlscan, virustotal
from amaan.reputation.base import SourceResult, SourceStatus, TTLCache
from amaan.reputation.feeds import FeedStore, normalize


class Reputation:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.feeds = FeedStore(s.urlhaus_key, s.feeds_enabled)
        self.client = httpx.AsyncClient(follow_redirects=False, trust_env=True)
        self.cache = TTLCache(3600)

    def start(self) -> None:
        self.feeds.start()

    async def aclose(self) -> None:
        await self.feeds.stop()
        await self.client.aclose()

    async def _cached(self, name: str, url: str, coro) -> SourceResult:
        key = f"{name}|{normalize(url)}"
        if (hit := self.cache.get(key)) is not None:
            return hit
        try:
            res = await asyncio.wait_for(coro, timeout=self.s.sources_timeout_s)
        except TimeoutError:
            res = SourceResult(source=name, kind="other", status=SourceStatus.timeout, detail="No answer in time.")
        if res.status is SourceStatus.ok:
            self.cache.put(key, res)
        return res

    async def check(self, url: str) -> list[SourceResult]:
        s = self.s
        remote = await asyncio.gather(
            self._cached("Google Safe Browsing", url, safebrowsing.check(url, s.safe_browsing_key, self.client)),
            self._cached("VirusTotal", url, virustotal.check(url, s.virustotal_key, self.client)),
            self._cached("urlscan.io", url, urlscan.check(url, s.urlscan_key, self.client, s.urlscan_wait_s)),
        )
        return [*self.feeds.check(url), *remote]
