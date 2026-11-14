"""Client for the browser sandbox (sandbox/browser, layer L6).

The worker opens one link in a fresh headless Chromium, runs the page's scripts, and
exits; Docker starts a clean container for the next link. So this client sends one link
at a time and waits a few seconds for the next container when the socket is not there yet.
Findings stay in memory for a few minutes (for the AI summary); nothing is logged.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from amaan.extract.urls import defang
from amaan.schemas import BrowserView, Download, ExpansionHop

CACHE_S = 300.0
CACHE_MAX = 100
MAX_SCREENSHOT = 300_000  # characters of the data: URL


class BrowserClient:
    def __init__(self, socket_path: str | None, timeout_s: float = 60.0, wait_s: float = 12.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.socket_path = socket_path or None
        self.wait_s = wait_s
        if transport is None and self.socket_path:
            transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        self._client = httpx.AsyncClient(base_url="http://browser", transport=transport, timeout=timeout_s,
                                         trust_env=False)
        self._lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, BrowserView]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.socket_path)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def reachable(self) -> bool:
        if not self.enabled:
            return False
        try:
            return (await self._client.get("/health", timeout=3)).status_code == 200
        except httpx.HTTPError:
            return False

    def cached(self, url: str) -> BrowserView | None:
        hit = self._cache.get(url.lower().rstrip("/"))
        return hit[1].model_copy() if hit and time.monotonic() - hit[0] < CACHE_S else None

    async def _post(self, url: str) -> dict | None:
        """One attempt per fresh container: retry while the next one is still starting."""
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                r = await self._client.post("/render", json={"url": url})
                if r.status_code != 503:
                    return r.json()
            except httpx.TimeoutException:
                raise
            except (httpx.HTTPError, ValueError):
                pass
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.5)

    async def render(self, url: str) -> BrowserView:
        if not self.enabled:
            return BrowserView(status="unavailable", message="The browser sandbox is not set up.")
        key = url.lower().rstrip("/")
        if hit := self.cached(url):
            return hit
        async with self._lock:
            try:
                data = await self._post(url)
            except httpx.TimeoutException:
                return BrowserView(status="error", message="The browser sandbox took too long to open the page.")
        if data is None:
            return BrowserView(status="unavailable", message="The browser sandbox is not running.")
        if not isinstance(data, dict) or "hops" not in data:
            return BrowserView(status="error", message="The browser sandbox could not open this link.")
        hops = [h for h in data.get("hops") or [] if isinstance(h, dict)]
        dl = data.get("download")
        shot = str(data.get("screenshot") or "")
        view = BrowserView(
            status="ok" if data.get("ok", True) else "error",
            message=str(data.get("message", ""))[:200],
            hops=[ExpansionHop(url=defang(str(h.get("url", ""))), status=h.get("status"), via=h.get("via"))
                  for h in hops[:15]],
            final_url=defang(str(data["final_url"])) if data.get("final_url") else None,
            stopped=str(data.get("stopped", ""))[:60],
            title=str(data.get("title", ""))[:200],
            asks_for=[a for a in data.get("asks_for") or [] if a in ("password", "code", "card")],
            human_check=bool(data.get("human_check")),
            download=Download(**{k: dl[k] for k in ("content_type", "size", "sha256", "filename", "complete") if k in dl})
            if isinstance(dl, dict) else None,
            elapsed_ms=int(data.get("elapsed_ms", 0) or 0),
            text=str(data.get("text", ""))[:4000],
            raw_hops=[str(h.get("url", "")) for h in hops[:15]],
            clickfix=bool(data.get("clickfix")),
            copies_text=bool(data.get("clipboard")),
            fake_window=[defang(str(x))[:120] for x in (data.get("fake_window") or [])[:3]],
            login_frames=[str(x)[:120] for x in (data.get("login_frames") or [])[:3]],
            screenshot=shot if shot.startswith("data:image/jpeg;base64,") and len(shot) <= MAX_SCREENSHOT else "",
            chrome_sandbox=data.get("chrome_sandbox") if isinstance(data.get("chrome_sandbox"), bool) else None,
            clipboard=[str(c)[:300] for c in (data.get("clipboard") or [])[:3]],
        )
        if len(self._cache) >= CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.monotonic(), view)
        return view.model_copy()
