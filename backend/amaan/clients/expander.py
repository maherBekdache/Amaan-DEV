"""Client for the expansion worker (sandbox/expander, layer L5).

The worker follows a link hop by hop inside its own container, whose only way out
is the egress proxy (public internet only). We talk to it over a Unix socket in a
volume shared by the two containers, so the worker cannot open a connection to us.

Its findings stay in memory for a few minutes so the AI summary can use the page
text without opening the link a second time; nothing is written to disk or logged.
"""

from __future__ import annotations

import time

import httpx

from amaan.extract.urls import defang
from amaan.schemas import Download, Expansion, ExpansionHop

CACHE_S = 300.0
CACHE_MAX = 200


class ExpanderClient:
    def __init__(self, socket_path: str | None, timeout_s: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.socket_path = socket_path or None
        self.timeout_s = timeout_s
        if transport is None and self.socket_path:
            transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        self._client = httpx.AsyncClient(base_url="http://expander", transport=transport, timeout=timeout_s,
                                         trust_env=False)
        self._cache: dict[str, tuple[float, Expansion]] = {}

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

    async def expand(self, url: str) -> Expansion:
        if not self.enabled:
            return Expansion(status="unavailable", message="The expansion worker is not set up.")
        key = url.lower().rstrip("/")
        now = time.monotonic()
        self._cache = {k: v for k, v in self._cache.items() if now - v[0] < CACHE_S}
        if key in self._cache:
            return self._cache[key][1].model_copy()
        try:
            r = await self._client.post("/expand", json={"url": url})
            data = r.json()
        except httpx.TimeoutException:
            return Expansion(status="error", message="The sandbox took too long to follow the link.")
        except (httpx.HTTPError, ValueError):
            return Expansion(status="unavailable", message="The expansion worker is not running.")
        if not isinstance(data, dict) or "hops" not in data:
            return Expansion(status="error", message="The expansion worker could not follow this link.")
        hops = [h for h in data.get("hops") or [] if isinstance(h, dict)]
        dl = data.get("download")
        exp = Expansion(
            status="ok" if data.get("ok", True) else "error",
            hops=[ExpansionHop(url=defang(str(h.get("url", ""))), status=h.get("status"), via=h.get("via"))
                  for h in hops[:12]],
            final_url=defang(str(data["final_url"])) if data.get("final_url") else None,
            stopped=str(data.get("stopped", ""))[:60],
            title=str(data.get("title", ""))[:200],
            asks_for=[a for a in data.get("asks_for") or [] if a in ("password", "code", "card")],
            human_check=bool(data.get("human_check")),
            download=Download(**{k: dl[k] for k in ("content_type", "size", "sha256", "filename", "complete") if k in dl})
            if isinstance(dl, dict) else None,
            elapsed_ms=int(data.get("elapsed_ms", 0) or 0),
            text=str(data.get("text", ""))[:4000],
            raw_hops=[str(h.get("url", "")) for h in hops[:12]],
        )
        if len(self._cache) >= CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (now, exp)
        return exp.model_copy()
