"""LLM providers behind one small interface: generate_json(system, user, schema) -> dict.

- OllamaProvider: local model, nothing leaves the machine (current choice).
- A cloud provider (e.g. Claude) can be added later by implementing the same
  method; it must be a team decision because message content would leave the
  machine (docs/DECISIONS.md).
"""

from __future__ import annotations

import json
import time
from typing import Protocol

import httpx


class LLMUnavailable(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    async def available(self) -> bool: ...

    async def generate_json(self, system: str, user: str, schema: dict) -> dict: ...


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0, transport=None) -> None:
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s, trust_env=False,
                                         transport=transport)
        self._avail_at = 0.0
        self._avail = False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def available(self) -> bool:
        """True when Ollama runs and the model is downloaded (checked at most every 30 s)."""
        if time.monotonic() - self._avail_at < 30:
            return self._avail
        try:
            r = await self._client.get("/api/tags", timeout=3)
            names = {m.get("name", "") for m in r.json().get("models", [])}
            self._avail = r.status_code == 200 and any(n == self.model or n.split(":")[0] == self.model for n in names)
        except Exception:  # not running, not reachable, unexpected answer
            self._avail = False
        self._avail_at = time.monotonic()
        return self._avail

    async def generate_json(self, system: str, user: str, schema: dict) -> dict:
        try:
            r = await self._client.post("/api/chat", json={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "format": schema,  # Ollama structured outputs: the reply must match this JSON schema
                "stream": False,
                "options": {"temperature": 0.1},
            })
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Ollama not reachable ({type(e).__name__})") from None
        if r.status_code != 200:
            raise LLMUnavailable(f"Ollama answered HTTP {r.status_code}")
        try:
            return json.loads(r.json()["message"]["content"])
        except (ValueError, KeyError, TypeError):
            raise LLMUnavailable("The model returned something that isn't valid JSON") from None
