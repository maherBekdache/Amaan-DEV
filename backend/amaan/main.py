"""Amaan API. Run with: uvicorn amaan.main:app --host 127.0.0.1 --port 8000"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from amaan import __version__
from amaan.analyzer import Analyzer
from amaan.api import whatsapp
from amaan.clients.urlvet import UrlVetClient
from amaan.ai.provider import OllamaProvider
from amaan.ai.reasoner import AIOpinion, first_link, second_opinion
from amaan.clients.lookyloo import LookylooClient
from amaan.reputation.aggregator import Reputation
from amaan.config import get_settings
from amaan.extract.qr import ImageRejected, available_decoders, decode_qr_codes
from amaan.schemas import Evidence, ExplainRequest, HealthResponse, InputType, LinkRequest, TextRequest

# Privacy: we log events and counts only, never message text, links or images.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("amaan")
# httpx logs every request URL at INFO, which would include the link being
# checked (URL.vet's ?url=...). Keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

settings = get_settings()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; "
       "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = UrlVetClient(settings.urlvet_base_url, settings.urlvet_timeout_s, settings.urlvet_concurrency)
    reputation = Reputation(settings)
    reputation.start()
    app.state.urlvet = client
    app.state.reputation = reputation
    app.state.analyzer = Analyzer(settings, client, reputation)
    app.state.ai = OllamaProvider(settings.ai_url, settings.ai_model) if settings.ai_enabled else None
    app.state.lookyloo = LookylooClient(settings.lookyloo_url, settings.lookyloo_timeout_s)
    log.info("Amaan %s started; URL.vet at %s", __version__, settings.urlvet_base_url)
    yield
    await client.aclose()
    await reputation.aclose()
    await app.state.lookyloo.aclose()
    if app.state.ai:
        await app.state.ai.aclose()


app = FastAPI(title="Amaan", version=__version__, lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"], allow_credentials=False)


GATEWAY_PATHS = ("/gateway/health", "/gateway/analyze/link", "/gateway/whatsapp")


def _host_allowed(host_header: str) -> bool:
    """Host-header allowlist (blocks DNS-rebinding attacks from websites)."""
    host = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header.split("]")[0] + "]"
    host = host.lower()
    for allowed in settings.allowed_hosts:
        if allowed == "*" or host == allowed or (allowed.startswith("*.") and host.endswith(allowed[1:])):
            return True
    return False


def _gateway_ok(request: Request) -> bool:
    """The phone app: allowed from the network only with the pairing token."""
    token = settings.phone_token
    auth = request.headers.get("authorization", "")
    return bool(token) and request.url.path in GATEWAY_PATHS and secrets.compare_digest(auth, f"Bearer {token}")


@app.middleware("http")
async def guard(request: Request, call_next):
    gateway = request.url.path in GATEWAY_PATHS
    if gateway and request.method == "OPTIONS":  # CORS preflight from the app's web build
        return Response(status_code=204, headers={
            "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST",
            "Access-Control-Allow-Headers": "Authorization, Content-Type", "Access-Control-Max-Age": "600"})
    if gateway:
        if not _gateway_ok(request):
            return JSONResponse({"detail": "Pair this app with Amaan first (missing or wrong token)."}, status_code=401,
                                headers={"Access-Control-Allow-Origin": "*"})
    elif not _host_allowed(request.headers.get("host", "")):
        return JSONResponse({"detail": "Invalid host header"}, status_code=400)
    # Reject oversized bodies before they are read or spooled to disk.
    limit = settings.max_import_bytes if request.url.path == "/import/chat" else settings.max_upload_bytes
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit + 64 * 1024:
        return JSONResponse({"detail": f"Upload too large (max {limit // (1024 * 1024)} MB)."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if gateway:
        response.headers["Access-Control-Allow-Origin"] = "*"
    if request.url.path.startswith(("/analyze", "/health", "/whatsapp", "/import", "/sources", "/ai", "/gateway", "/phone")):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Content-Security-Policy"] = CSP
    return response


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    st = request.app.state
    uv = await st.urlvet.health()
    ai = {"available": await st.ai.available() if st.ai else False,
          "model": settings.ai_model if st.ai else None, "provider": "ollama" if st.ai else None}
    return HealthResponse(status="ok", version=__version__, urlvet=uv,
                          qr_decoders=available_decoders(settings.wechat_model_dir), ai=ai,
                          lookyloo={"enabled": st.lookyloo.enabled, "reachable": await st.lookyloo.reachable()})


@app.post("/analyze/text", response_model=Evidence)
async def analyze_text(req: TextRequest, request: Request) -> Evidence:
    if not (req.text.strip() or (req.html or "").strip() or (req.uri_list or "").strip()):
        raise HTTPException(400, "Nothing to analyze: send text, html or uri_list.")
    return await request.app.state.analyzer.analyze_text(req)


@app.post("/analyze/link", response_model=Evidence)
async def analyze_link(req: LinkRequest, request: Request) -> Evidence:
    """Hybrid mode: the app analyzed the message on the device and sends only links."""
    if not any(u.strip() for u in req.urls):
        raise HTTPException(400, "Send at least one link.")
    return await request.app.state.analyzer.analyze_links(req.urls)


# --- phone app (hybrid mode) ---------------------------------------------------
# The phone analyzes messages and QR codes itself and sends only links here.
# Reachable from the local network only when the phone gateway is enabled
# (start-everything.bat / -Phone) and only with the pairing token.


@app.get("/gateway/health")
async def gateway_health(request: Request) -> dict:
    uv = await request.app.state.urlvet.health()
    return {"status": "ok", "version": __version__, "link_sandbox": bool(uv.get("reachable"))}


@app.post("/gateway/analyze/link", response_model=Evidence)
async def gateway_analyze_link(req: LinkRequest, request: Request) -> Evidence:
    if not any(u.strip() for u in req.urls):
        raise HTTPException(400, "Send at least one link.")
    return await request.app.state.analyzer.analyze_links(req.urls)


@app.get("/phone/pairing")
async def phone_pairing() -> dict:
    """For the laptop screen only (host check): what the 'Connect phone' QR contains."""
    if not (settings.phone_token and settings.phone_url):
        return {"enabled": False, "message": "Start Amaan with start-everything.bat (or 'up -Phone') to connect a phone."}
    return {"enabled": True, "server": settings.phone_url, "token": settings.phone_token,
            "pair_uri": f"amaan://pair?server={settings.phone_url}&token={settings.phone_token}"}


@app.post("/ai/explain", response_model=AIOpinion)
async def ai_explain(req: ExplainRequest, request: Request) -> AIOpinion:
    """AI second opinion on a result. Local model; Lookyloo opens the link first if available."""
    st = request.app.state
    if not st.ai:
        return AIOpinion(available=False, message="AI is turned off (AMAAN_AI_ENABLED=0).")
    capture = None
    link = first_link(req.evidence)
    if req.open_page and link and st.lookyloo.enabled:
        capture = await st.lookyloo.capture(link)
    return await second_opinion(st.ai, req.evidence, req.text, capture)


@app.get("/sources")
async def sources(request: Request) -> dict:
    """Which reputation sources are set up (no secrets)."""
    s = settings
    feeds = request.app.state.reputation.feeds
    return {"sources": [
        {"name": f.name, "kind": "blocklist", "ready": bool(f.loaded_at), "entries": len(f.urls)} for f in feeds.feeds
    ] + [
        {"name": "Google Safe Browsing", "kind": "blocklist", "ready": bool(s.safe_browsing_key)},
        {"name": "VirusTotal", "kind": "engines", "ready": bool(s.virustotal_key)},
        {"name": "urlscan.io", "kind": "sandbox", "ready": bool(s.urlscan_key)},
        {"name": "URL.vet", "kind": "sandbox", "ready": True},
    ]}


@app.post("/analyze/image", response_model=Evidence)
async def analyze_image(request: Request, file: UploadFile = File(...),
                        source: str = Form("image")) -> Evidence:
    input_type = InputType.camera if source == "camera" else InputType.image
    try:
        data = await file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, f"Image too large (max {settings.max_upload_bytes // (1024 * 1024)} MB).")
        try:
            qr = await run_in_threadpool(
                decode_qr_codes, data, max_pixels=settings.max_image_pixels,
                max_codes=settings.max_qr_codes_per_image, model_dir=settings.wechat_model_dir,
            )
        except ImageRejected as e:
            raise HTTPException(415, str(e)) from None
    finally:
        # Closing the UploadFile deletes any temporary file it spooled to disk.
        await file.close()
        data = b""
    return await request.app.state.analyzer.analyze_qr(qr, input_type)


app.include_router(whatsapp.router)


# --- built frontend (production / Docker) ------------------------------------
_dist = Path(settings.frontend_dist) if settings.frontend_dist else None
if _dist and (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")
    if (_dist / "examples").exists():  # built-in demo examples (safe, bundled with the app)
        app.mount("/examples", StaticFiles(directory=_dist / "examples"), name="examples")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_dist / "index.html")
