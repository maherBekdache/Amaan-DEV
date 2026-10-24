"""VirusTotal v3: looks up what ~70 security engines already said about the link.

Lookup only: we never submit new links (submitting would publish them to
VirusTotal's customers). Free keys allow 4 lookups per minute.
"""

from __future__ import annotations

import base64
from functools import partial

import httpx

from amaan.reputation.base import RateLimiter, SourceResult, SourceStatus, SourceVerdict

API = "https://www.virustotal.com/api/v3/urls/"
NAME = "VirusTotal"
limiter = RateLimiter(4, 60.0)
_result = partial(SourceResult, source=NAME, kind="engines")


def url_id(url: str) -> str:
    u = url if "://" in url else "http://" + url
    return base64.urlsafe_b64encode(u.encode()).decode().rstrip("=")


async def check(url: str, api_key: str | None, client: httpx.AsyncClient) -> SourceResult:
    if not api_key:
        return _result(status=SourceStatus.not_configured,
                       detail="Needs a free VirusTotal API key (AMAAN_VIRUSTOTAL_KEY).")
    if not await limiter.acquire(max_wait=15):
        return _result(status=SourceStatus.rate_limited,
                       detail="Free plan allows 4 lookups a minute; try again shortly.")
    try:
        r = await client.get(API + url_id(url), headers={"x-apikey": api_key}, timeout=15)
    except httpx.TimeoutException:
        return _result(status=SourceStatus.timeout, detail="No answer in time.")
    except httpx.HTTPError:
        return _result(status=SourceStatus.error, detail="Not reachable.")
    if r.status_code == 404:
        return _result(status=SourceStatus.ok, verdict=SourceVerdict.unknown,
                       detail="VirusTotal has never seen this link (new links are common in scams).")
    if r.status_code == 429:
        return _result(status=SourceStatus.rate_limited, detail="Quota reached.")
    if r.status_code != 200:
        return _result(status=SourceStatus.error, detail=f"HTTP {r.status_code}.")
    try:
        stats = r.json()["data"]["attributes"]["last_analysis_stats"]
    except (ValueError, KeyError, TypeError):
        return _result(status=SourceStatus.error, detail="Unreadable answer.")
    bad, sus = int(stats.get("malicious", 0)), int(stats.get("suspicious", 0))
    total = sum(int(v) for v in stats.values() if isinstance(v, int))
    detail = f"{bad} of {total} engines say malicious, {sus} suspicious."
    if bad >= 2:
        verdict = SourceVerdict.malicious
    elif bad == 1 or sus >= 2:
        verdict = SourceVerdict.suspicious
    else:
        verdict = SourceVerdict.clean
    return _result(status=SourceStatus.ok, verdict=verdict, detail=detail)
