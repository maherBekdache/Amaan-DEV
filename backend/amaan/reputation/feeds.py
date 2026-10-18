"""Downloaded phishing / malware link lists, checked locally.

Nothing about the user's link is sent: the whole list is downloaded on a
schedule and looked up in memory. Lists: OpenPhish (community feed, research
use) and URLhaus (abuse.ch, free Auth-Key). PhishTank is already checked by
URL.vet.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from amaan.reputation.base import SourceResult, SourceStatus, SourceVerdict

log = logging.getLogger("amaan.feeds")

# Hosts where anyone can publish: a listed page there says nothing about other pages.
SHARED_HOSTS = ("google.com", "googleusercontent.com", "github.io", "dropbox.com", "onedrive.live.com",
                "sharepoint.com", "blogspot.com", "weebly.com", "wixsite.com", "000webhostapp.com",
                "firebaseapp.com", "web.app", "pages.dev", "netlify.app", "vercel.app", "glitch.me",
                "forms.gle", "docs.google.com", "sites.google.com", "notion.site", "telegra.ph")


def normalize(url: str) -> str:
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    try:
        p = urlsplit(u)
    except ValueError:
        return url.strip().lower()
    host = (p.hostname or "").lower().removeprefix("www.")
    path = p.path or "/"
    return f"{host}{path}" + (f"?{p.query}" if p.query else "")


def host_of(url: str) -> str:
    return normalize(url).split("/", 1)[0]


def is_shared(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in SHARED_HOSTS)


@dataclass
class Feed:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    urls: set[str] = field(default_factory=set)
    hosts: set[str] = field(default_factory=set)
    loaded_at: float = 0.0
    error: str = ""

    def load_text(self, text: str) -> None:
        urls, hosts = set(), set()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.add(normalize(line))
            h = host_of(line)
            if h and not is_shared(h):
                hosts.add(h)
        self.urls, self.hosts, self.loaded_at, self.error = urls, hosts, time.time(), ""

    def check(self, url: str) -> SourceResult:
        if not self.loaded_at:
            return SourceResult(source=self.name, kind="blocklist", status=SourceStatus.error, community=True,
                                detail=self.error or "List not downloaded yet.")
        n, h = normalize(url), host_of(url)
        if n in self.urls:
            return SourceResult(source=self.name, kind="blocklist", status=SourceStatus.ok, community=True,
                                verdict=SourceVerdict.malicious, detail="This exact link is on the list.")
        if h in self.hosts:
            return SourceResult(source=self.name, kind="blocklist", status=SourceStatus.ok, community=True,
                                verdict=SourceVerdict.malicious, detail="Other pages on this site are on the list.")
        return SourceResult(source=self.name, kind="blocklist", status=SourceStatus.ok, community=True,
                            verdict=SourceVerdict.clean, detail=f"Not among {len(self.urls):,} listed links.")


class FeedStore:
    def __init__(self, urlhaus_key: str | None, enabled: bool, refresh_s: float = 6 * 3600) -> None:
        self.enabled = enabled
        self.refresh_s = refresh_s
        self.feeds = [Feed("OpenPhish", "https://openphish.com/feed.txt")]
        if urlhaus_key:
            self.feeds.append(Feed("URLhaus", "https://urlhaus.abuse.ch/downloads/text_online/",
                                   headers={"Auth-Key": urlhaus_key}))
        self.task: asyncio.Task | None = None

    async def refresh_once(self, client: httpx.AsyncClient) -> None:
        for f in self.feeds:
            try:
                r = await client.get(f.url, headers=f.headers, timeout=60)
                r.raise_for_status()
                f.load_text(r.text)
                log.info("%s list loaded (%d links)", f.name, len(f.urls))
            except Exception as e:  # keep the previous copy
                f.error = f"Download failed ({type(e).__name__})."
                log.warning("%s list download failed: %s", f.name, type(e).__name__)

    async def run(self) -> None:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            while True:
                await self.refresh_once(client)
                await asyncio.sleep(self.refresh_s)

    def start(self) -> None:
        if self.enabled and self.task is None:
            self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None

    def check(self, url: str) -> list[SourceResult]:
        if not self.enabled:
            return [SourceResult(source="Downloaded lists", kind="blocklist", status=SourceStatus.not_configured,
                                 community=True, detail="Turned off (AMAAN_FEEDS_ENABLED=0).")]
        out = [f.check(url) for f in self.feeds]
        if len(self.feeds) == 1:
            out.append(SourceResult(source="URLhaus", kind="blocklist", status=SourceStatus.not_configured,
                                    community=True, detail="Needs a free abuse.ch Auth-Key (AMAAN_URLHAUS_KEY)."))
        return out
