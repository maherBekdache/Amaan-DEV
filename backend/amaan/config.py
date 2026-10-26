"""Runtime settings, read from environment variables (prefix AMAAN_)."""

import ipaddress
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_HOSTS = ["localhost", "127.0.0.1", "amaan", "testserver"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AMAAN_", env_file=".env", extra="ignore")

    # URL.vet runs as a separate service (see docs/DECISIONS.md). Only it ever
    # contacts untrusted destinations; we only talk to its API.
    urlvet_base_url: str = "http://localhost:8080"
    urlvet_timeout_s: float = 25.0  # URL.vet itself drops checks after 15 s
    urlvet_concurrency: int = 3  # URL.vet allows 20 requests/minute per client IP

    # Input limits
    max_text_chars: int = 20_000
    max_urls_per_request: int = 10
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    max_qr_codes_per_image: int = 10

    # Optional WeChat QR CNN model folder (detect.prototxt, detect.caffemodel,
    # sr.prototxt, sr.caffemodel). Without it, the WeChat detector still runs
    # in its non-CNN mode.
    wechat_model_dir: str | None = None

    # Hosts allowed in the Host header. Blocks DNS-rebinding attacks from
    # random websites against this local API.
    # Comma-separated in the environment, e.g. AMAAN_ALLOWED_HOSTS=localhost,127.0.0.1,*.example.dev
    allowed_hosts: Annotated[list[str], NoDecode] = DEFAULT_HOSTS
    # Extra browser origins allowed by CORS (the Vite dev server). The built
    # frontend is served from the same origin and needs none.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # WhatsApp (optional, Milestone 3). The bridge is a separate Node service;
    # it may only forward messages if it presents this shared token.
    whatsapp_bridge_url: str = "http://localhost:8090"
    bridge_token: str | None = None
    # Chat-export import (.txt / .zip with photos)
    max_import_bytes: int = 60 * 1024 * 1024
    max_urls_per_import: int = 15

    # Multi-source link reputation (see docs/DECISIONS.md, D11). Every source
    # sees only the link. Sources without a key are skipped ("not set up").
    feeds_enabled: bool = True  # download OpenPhish (+ URLhaus with a key) and check locally
    urlhaus_key: str | None = None
    safe_browsing_key: str | None = None  # hash prefixes only
    virustotal_key: str | None = None  # lookup only, never submits
    urlscan_key: str | None = None  # private scans
    sources_timeout_s: float = 45.0
    urlscan_wait_s: float = 40.0

    # AI summary (docs/DECISIONS.md D12, D17). "ollama" = local Ollama API; "openai" = any
    # OpenAI-compatible server (LM Studio, vLLM, llama.cpp, or a cloud model once approved).
    ai_enabled: bool = True
    ai_provider: str = "ollama"
    ai_url: str = "http://localhost:11434"
    ai_model: str = "qwen2.5:3b"  # multilingual incl. Arabic; use qwen2.5:7b with a GPU
    ai_api_key: str | None = None
    # A model that is not on this computer only gets the evidence (signals, source answers,
    # defanged link), never the message or page text, unless this is set (needs owner approval).
    ai_remote_may_read_messages: bool = False
    # Speech-to-text for WhatsApp voice notes: a local OpenAI-style /v1/audio/transcriptions server.
    stt_url: str | None = None
    stt_model: str = ""
    # Lookyloo (optional sandbox that opens the page and records everything it loads)
    lookyloo_url: str | None = None
    lookyloo_timeout_s: float = 60.0

    # Phone app gateway (hybrid mode): LAN address shown in the pairing QR, and
    # the secret the app must send. Both set by the scripts; off when empty.
    phone_url: str | None = None
    phone_token: str | None = None

    # Folder with the built frontend; served at / when it exists.
    frontend_dist: str | None = None

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, v):
        if isinstance(v, str):
            hosts = [h.strip() for h in v.split(",") if h.strip()]
            return hosts or DEFAULT_HOSTS
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_local_url(url: str) -> bool:
    """True for this computer, a Docker service name, or a private-network address."""
    host = (urlsplit(url if "://" in url else "//" + url).hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or (host and "." not in host) or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local
