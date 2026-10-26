"""Optional speech-to-text for WhatsApp voice notes (Milestone 2 hook).

Talks to a speech-to-text server running on this computer, using the common
OpenAI-style route POST /v1/audio/transcriptions (served by faster-whisper /
speaches servers, and easy to put in front of the team's Lebanese model).
Off unless AMAAN_STT_URL is set. Audio never goes to a cloud service: only
local addresses are accepted (hard rule 2), and nothing is written to disk.
"""

from __future__ import annotations

import httpx

from amaan.config import is_local_url


class Transcriber:
    def __init__(self, base_url: str | None, model: str = "", timeout_s: float = 120.0, transport=None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.error = "" if not self.base_url or is_local_url(self.base_url) else \
            "AMAAN_STT_URL must point to this computer (audio never leaves it)."
        self._client = httpx.AsyncClient(timeout=timeout_s, trust_env=False, transport=transport)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url) and not self.error

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str | None:
        """The transcript, or None when transcription is off or failed."""
        if not self.enabled or not audio:
            return None
        data = {"model": self.model} if self.model else {}
        try:
            r = await self._client.post(f"{self.base_url}/v1/audio/transcriptions",
                                        files={"file": (filename, audio, "audio/ogg")}, data=data)
            r.raise_for_status()
            return str(r.json().get("text", "")).strip() or None
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
