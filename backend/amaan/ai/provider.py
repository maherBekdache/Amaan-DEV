"""LLM providers behind one small interface: available() and generate_json(system, user, schema).

- OllamaProvider: a local model through Ollama (the current demo).
- OpenAICompatibleProvider: any server speaking the OpenAI chat API: LM Studio, vLLM or
  llama.cpp on this computer or the lab GPU, or a cloud model once the owner approves it.
`make_provider` picks one from the settings. A provider that is not on this computer
(`may_read_messages` False) only ever receives the evidence, never the message text.
"""

from __future__ import annotations

import json
import time
from typing import Protocol

import httpx

from amaan.config import Settings, is_local_url


class LLMUnavailable(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str
    may_read_messages: bool
    setup_hint: str

    async def available(self) -> bool: ...

    async def generate_json(self, system: str, user: str, schema: dict) -> dict: ...

    async def aclose(self) -> None: ...


class _Base:
    name = "llm"
    tags_path = "/"

    def __init__(self, base_url: str, model: str, *, api_key: str | None = None, may_read_messages: bool = True,
                 timeout_s: float = 120.0, transport=None) -> None:
        self.model = model
        self.may_read_messages = may_read_messages
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s, trust_env=False,
                                         transport=transport, headers=headers)
        self._avail_at = 0.0
        self._avail = False

    async def aclose(self) -> None:
        await self._client.aclose()

    def _has_model(self, body: dict) -> bool:
        raise NotImplementedError

    async def available(self) -> bool:
        """True when the server runs and has the model (checked at most every 30 s)."""
        if time.monotonic() - self._avail_at < 30:
            return self._avail
        try:
            r = await self._client.get(self.tags_path, timeout=3)
            self._avail = r.status_code == 200 and self._has_model(r.json())
        except Exception:  # not running, not reachable, unexpected answer
            self._avail = False
        self._avail_at = time.monotonic()
        return self._avail

    async def _post(self, path: str, body: dict) -> dict:
        try:
            r = await self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"{self.name} not reachable ({type(e).__name__})") from None
        if r.status_code != 200:
            raise LLMUnavailable(f"{self.name} answered HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise LLMUnavailable(f"{self.name} returned an unreadable answer") from None


def _parse(content: object) -> dict:
    try:
        out = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        out = None
    if not isinstance(out, dict):
        raise LLMUnavailable("The model returned something that isn't valid JSON")
    return out


class OllamaProvider(_Base):
    name = "ollama"
    tags_path = "/api/tags"

    @property
    def setup_hint(self) -> str:
        return f"Local AI is off: start Ollama and run 'ollama pull {self.model}'."

    def _has_model(self, body: dict) -> bool:
        names = {m.get("name", "") for m in body.get("models", [])}
        return any(n == self.model or n.split(":")[0] == self.model for n in names)

    async def generate_json(self, system: str, user: str, schema: dict) -> dict:
        body = await self._post("/api/chat", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,  # Ollama structured outputs: the reply must match this JSON schema
            "stream": False,
            "options": {"temperature": 0.1},
        })
        return _parse((body.get("message") or {}).get("content"))


class OpenAICompatibleProvider(_Base):
    name = "openai-compatible"
    tags_path = "/v1/models"

    @property
    def setup_hint(self) -> str:
        return f"The AI server is not reachable or does not serve the model '{self.model}'."

    def _has_model(self, body: dict) -> bool:
        return any(m.get("id") == self.model for m in body.get("data", []))

    async def generate_json(self, system: str, user: str, schema: dict) -> dict:
        body = await self._post("/v1/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "amaan_summary", "schema": schema}},
            "temperature": 0.1,
        })
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMUnavailable("The model returned an unexpected answer") from None
        return _parse(content)


def make_provider(s: Settings) -> LLMProvider | None:
    if not s.ai_enabled:
        return None
    cls = OpenAICompatibleProvider if s.ai_provider == "openai" else OllamaProvider
    return cls(s.ai_url, s.ai_model, api_key=s.ai_api_key,
               may_read_messages=is_local_url(s.ai_url) or s.ai_remote_may_read_messages)
