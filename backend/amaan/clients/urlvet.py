"""Client for a self-hosted URL.vet instance (separate AGPL service).

We only call its HTTP API. URL.vet follows shorteners/redirects and loads
the page in its own headless-Chrome container; our process never contacts
the destination. Failures are returned as a status, never as a fake "safe".
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from amaan.extract.urls import defang
from amaan.schemas import UrlVetResult, UrlVetStatus

log = logging.getLogger(__name__)


def _int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _strs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v]


def parse_report(data: dict[str, Any]) -> UrlVetResult:
    """Map URL.vet's /api/v1/analyze JSON onto our UrlVetResult."""
    result = data.get("result") or {}
    reasons = result.get("reasons") or {}

    chain: list[str] = []
    for key in ("short_link", "redirected_from"):
        block = data.get(key) or {}
        if isinstance(block, dict):
            chain = _strs(block.get("chain")) or chain
    redirect = ((data.get("analysis") or {}).get("redirection_result") or {})
    if not chain:
        chain = _strs(redirect.get("chain"))
    final_url = redirect.get("final_url") or data.get("url")

    feeds = data.get("threat_feeds") or {}
    sb = data.get("safe_browsing") or {}
    wr = data.get("web_risk") or {}
    sources = _strs(feeds.get("sources"))
    if sb.get("listed"):
        sources.append("Google Safe Browsing")
    if wr.get("listed"):
        sources.append("Google Web Risk")

    short = data.get("short_link") or {}
    neutral = _strs(reasons.get("neutral_reasons"))
    if isinstance(short, dict) and short and short.get("resolved") is False:
        neutral.append("URL.vet could not find where this short link leads.")

    return UrlVetResult(
        status=UrlVetStatus.ok,
        verdict=result.get("verdict"),
        final_score=_int(result.get("final_score")),
        trust_score=_int(result.get("trust_score")),
        risk_score=_int(result.get("risk_score")),
        bad_reasons=_strs(reasons.get("bad_reasons")),
        good_reasons=_strs(reasons.get("good_reasons")),
        neutral_reasons=neutral,
        final_url=defang(str(final_url)) if final_url else None,
        redirect_chain=[defang(u) for u in chain][:10],
        threat_listed=bool(feeds.get("listed") or sb.get("listed") or wr.get("listed")),
        threat_sources=sources,
        incomplete=bool(data.get("incomplete")),
    )


class UrlVetClient:
    def __init__(self, base_url: str, timeout_s: float = 25.0, concurrency: int = 3,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._sem = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=3.0),
            follow_redirects=False,  # never follow anything on our side
            trust_env=False,  # never route local calls through a system proxy
            transport=transport,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            r = await self._client.get("/health", timeout=3.0)
            ok = r.status_code < 500
        except httpx.HTTPError:
            ok = False
        return {"reachable": ok, "base_url": self.base_url,
                "latency_ms": int((time.perf_counter() - t0) * 1000)}

    async def analyze(self, url: str) -> UrlVetResult:
        async with self._sem:
            t0 = time.perf_counter()
            res = await self._analyze(url)
            res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return res

    async def _analyze(self, url: str) -> UrlVetResult:
        try:
            r = await self._client.get("/api/v1/analyze", params={"url": url[:2048]})
            if r.status_code == 400 and "://" not in url:
                # Bare "domain/path" forms: retry once with an explicit scheme.
                r = await self._client.get("/api/v1/analyze", params={"url": ("https://" + url)[:2048]})
        except httpx.TimeoutException:
            return UrlVetResult(status=UrlVetStatus.timeout,
                                message=f"URL.vet did not answer within {self.timeout_s:.0f} s.")
        except httpx.HTTPError:
            return UrlVetResult(status=UrlVetStatus.unavailable,
                                message="URL.vet is not running or not reachable.")

        if r.status_code == 429:
            return UrlVetResult(status=UrlVetStatus.rate_limited,
                                message="URL.vet rate limit reached (20 checks per minute). Try again shortly.")
        if r.status_code in (400, 422):
            try:
                msg = r.json().get("error", "")
            except ValueError:
                msg = ""
            return UrlVetResult(status=UrlVetStatus.rejected,
                                message=f"URL.vet could not analyze this link ({msg or r.status_code}).")
        if r.status_code != 200:
            return UrlVetResult(status=UrlVetStatus.error, message=f"URL.vet returned HTTP {r.status_code}.")
        try:
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError
            return parse_report(data)
        except ValueError:
            return UrlVetResult(status=UrlVetStatus.error, message="URL.vet returned an unreadable response.")
