"""Amaan API. Run with: uvicorn amaan.main:app --host 127.0.0.1 --port 8000"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from amaan import __version__
from amaan.analyzer import Analyzer
from amaan.clients.urlvet import UrlVetClient
from amaan.config import get_settings
from amaan.extract.qr import ImageRejected, available_decoders, decode_qr_codes
from amaan.schemas import Evidence, HealthResponse, InputType, TextRequest

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
    app.state.urlvet = client
    app.state.analyzer = Analyzer(settings, client)
    log.info("Amaan %s started; URL.vet at %s", __version__, settings.urlvet_base_url)
    yield
    await client.aclose()


app = FastAPI(title="Amaan", version=__version__, lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"], allow_credentials=False)


@app.middleware("http")
async def guard(request: Request, call_next):
    # Reject oversized bodies before they are read or spooled to disk.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_upload_bytes + 64 * 1024:
        return JSONResponse({"detail": f"Upload too large (max {settings.max_upload_bytes // (1024 * 1024)} MB)."},
                            status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path.startswith(("/analyze", "/health")):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Content-Security-Policy"] = CSP
    return response


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    uv = await request.app.state.urlvet.health()
    return HealthResponse(status="ok", version=__version__, urlvet=uv,
                          qr_decoders=available_decoders(settings.wechat_model_dir))


@app.post("/analyze/text", response_model=Evidence)
async def analyze_text(req: TextRequest, request: Request) -> Evidence:
    if not (req.text.strip() or (req.html or "").strip() or (req.uri_list or "").strip()):
        raise HTTPException(400, "Nothing to analyze: send text, html or uri_list.")
    return await request.app.state.analyzer.analyze_text(req)


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


# --- built frontend (production / Docker) ------------------------------------
_dist = Path(settings.frontend_dist) if settings.frontend_dist else None
if _dist and (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_dist / "index.html")
