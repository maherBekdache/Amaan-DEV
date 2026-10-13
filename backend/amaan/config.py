"""Runtime settings, read from environment variables (prefix AMAAN_)."""

from functools import lru_cache
from typing import Annotated

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
    # Comma-separated in the environment, e.g. in GitHub Codespaces:
    # AMAAN_ALLOWED_HOSTS=localhost,127.0.0.1,*.app.github.dev
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
