"""Client for a self-hosted Lookyloo (separate BSD-3 service, unmodified).

Lookyloo opens the link inside its own container (Playwright) and records
the full redirect chain and the page content. We use its 'ai_export'
(redirects + page text as markdown) as evidence for the AI reasoning step.
Lookyloo is configured private: captures are not public, internal network
addresses are refused, and every third-party module is off (infra/lookyloo).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

DONE = 1  # Lookyloo's capture status code for 'finished'


@dataclass
class Capture:
    ok: bool
    message: str = ""
    redirects: list[str] = field(default_factory=list)
    page_text: str = ""  # page as markdown, truncated
    uuid: str | None = None


class LookylooClient:
    def __init__(self, base_url: str | None, timeout_s: float = 60.0, transport=None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout_s = timeout_s
        self._client = httpx.AsyncClient(base_url=self.base_url or "http://disabled", timeout=15,
                                         trust_env=False, transport=transport)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def reachable(self) -> bool:
        if not self.enabled:
            return False
        try:
            return (await self._client.get("/json/stats", timeout=3)).status_code < 500
        except httpx.HTTPError:
            return False

    async def capture(self, url: str, poll_s: float = 3.0) -> Capture:
        if not self.enabled:
            return Capture(False, "Lookyloo is not set up.")
        try:
            r = await self._client.post("/submit", json={
                "url": url if "://" in url else "http://" + url,
                "listing": False, "allow_tracking": False,  # private capture, refuse tracking consent
            })
            r.raise_for_status()
            body = r.json()
            uuid = body["uuid"] if isinstance(body, dict) else str(body)
            waited = 0.0
            while waited < self.timeout_s:
                await asyncio.sleep(poll_s)
                waited += poll_s
                st = (await self._client.get(f"/json/{uuid}/status")).json().get("status_code")
                if st == DONE:
                    break
            else:
                return Capture(False, "Lookyloo didn't finish the capture in time.", uuid=uuid)
            exp = (await self._client.get(f"/json/{uuid}/ai_export")).json()
            if "error" in exp:
                return Capture(False, f"Lookyloo couldn't load the page ({exp['error'][:120]}).", uuid=uuid)
            data = exp.get("response") or {}
            redirects = [str(e.get("url", "")) for e in data.get("redirects") or [] if isinstance(e, dict)]
            text = str(data.get("html_as_markdown") or "")[:3000]
            return Capture(True, redirects=redirects[:15], page_text=text, uuid=uuid)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            return Capture(False, f"Lookyloo is not reachable ({type(e).__name__}).")
