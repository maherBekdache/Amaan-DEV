"""urlscan.io: a PRIVATE remote scan of the link (visible only to our account).

Submits the link with visibility=private, then polls for the verdict
(usually 10-30 s). Free accounts have a small private-scan quota.
"""

from __future__ import annotations

import asyncio
from functools import partial

import httpx

from amaan.reputation.base import SourceResult, SourceStatus, SourceVerdict

API = "https://urlscan.io/api/v1"
NAME = "urlscan.io"
_result = partial(SourceResult, source=NAME, kind="sandbox")


async def check(url: str, api_key: str | None, client: httpx.AsyncClient, wait_s: float = 40.0,
                first_wait: float = 10.0, poll_every: float = 5.0) -> SourceResult:
    if not api_key:
        return _result(status=SourceStatus.not_configured,
                       detail="Needs a free urlscan.io API key (AMAAN_URLSCAN_KEY).")
    headers = {"API-Key": api_key}
    target = url if "://" in url else "http://" + url
    try:
        r = await client.post(f"{API}/scan/", headers=headers, json={"url": target, "visibility": "private"}, timeout=15)
        if r.status_code == 429:
            return _result(status=SourceStatus.rate_limited, detail="Scan quota reached.")
        if r.status_code >= 400:
            msg = ""
            try:
                msg = r.json().get("message", "")
            except ValueError:
                pass
            return _result(status=SourceStatus.error,
                           detail=f"Scan refused ({msg or r.status_code}).")
        uuid = r.json()["uuid"]
        await asyncio.sleep(first_wait)
        waited = first_wait
        while waited <= wait_s:
            res = await client.get(f"{API}/result/{uuid}/", headers=headers, timeout=15)
            if res.status_code == 200:
                overall = (res.json().get("verdicts") or {}).get("overall") or {}
                if overall.get("malicious"):
                    brands = ", ".join(overall.get("brands") or [])
                    return _result(status=SourceStatus.ok,
                                   verdict=SourceVerdict.malicious,
                                   detail="Its scanner judged the page malicious" + (f" (imitates {brands})." if brands else "."))
                score = overall.get("score", 0) or 0
                return _result(status=SourceStatus.ok,
                               verdict=SourceVerdict.suspicious if score > 0 else SourceVerdict.clean,
                               detail=f"Scanned privately; risk score {score}.")
            await asyncio.sleep(poll_every)
            waited += max(poll_every, 0.01)
        return _result(status=SourceStatus.timeout, detail="Scan didn't finish in time.")
    except httpx.TimeoutException:
        return _result(status=SourceStatus.timeout, detail="No answer in time.")
    except (httpx.HTTPError, KeyError, ValueError):
        return _result(status=SourceStatus.error, detail="Not reachable.")
