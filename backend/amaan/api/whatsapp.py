"""WhatsApp features (Milestone 3).

- /import/chat: analyze a WhatsApp "Export chat" file (.txt or .zip). Zero-risk:
  no WhatsApp connection at all.
- /whatsapp/*: talk to the optional bridge service (Baileys), which watches only
  the chats the user selected and forwards new messages to /whatsapp/ingest.

Privacy: nothing here writes to disk. Flagged live messages are kept in RAM
(last 50) so the user can see them; they disappear on restart or "Clear".
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import deque
from datetime import datetime, timezone
from itertools import count

import httpx
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from amaan.analyzer import Analyzer, LinkBudget, _key
from amaan.config import get_settings
from amaan.extract.qr import ImageRejected, decode_qr_codes
from amaan.extract.urls import extract_urls
from amaan.importers.whatsapp_export import ChatExport, ExportRejected, load_export
from amaan.schemas import (
    Evidence, EvidenceLabel, ImportFinding, ImportReport, InputType, RiskLevel, Severity, Signal, TextRequest,
    WhatsAppAlert,
)
from amaan.scoring import aggregate, local_rules, text_cues

router = APIRouter()
log = logging.getLogger("amaan.whatsapp")
settings = get_settings()

_alerts: deque[WhatsAppAlert] = deque(maxlen=50)
_alert_ids = count(1)
_stats = {"checked": 0}
_SNIPPET = 400


# --- chat export import ---------------------------------------------------------


def _local_priority(text: str) -> int:
    """How suspicious a message looks before any network check (for ordering)."""
    sev = {"high": 3, "medium": 2, "low": 1}
    best = 0
    for u in extract_urls(text, limit=10).urls:
        for s in local_rules.url_signals(u):
            best = max(best, sev.get(s.severity.value, 0))
    return best + (1 if text_cues.text_cue_signals(text) else 0)


async def analyze_export(analyzer: Analyzer, export: ChatExport) -> ImportReport:
    budget = LinkBudget(settings.max_urls_per_import)
    warnings: list[str] = []
    candidates = [m for m in export.messages if extract_urls(m.text, limit=1).urls
                  or text_cues.text_cue_signals(m.text)][:5000]

    # Check the most suspicious-looking (then newest) links first, all at once.
    ordered = sorted(candidates, key=lambda m: (-_local_priority(m.text), -m.index))
    keys: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in ordered:
        for u in extract_urls(m.text, limit=10).urls:
            k = _key(u.url)
            if k not in seen:
                seen.add(k)
                keys.append((k, u.url))
    to_fetch = keys[: budget.remaining]
    results = await asyncio.gather(*(analyzer.urlvet.analyze(url) for _, url in to_fetch))
    for (k, _), r in zip(to_fetch, results):
        budget.cache[k] = r
    budget.remaining = 0
    if len(keys) > len(to_fetch):
        warnings.append(f"{len(keys)} different links found; the {len(to_fetch)} most suspicious were "
                        f"checked in the sandbox, the rest only with Amaan's own rules.")

    findings: list[ImportFinding] = []
    for m in candidates:
        ev = await analyzer.analyze_text(TextRequest(text=m.text), budget)
        if ev.risk_level is not RiskLevel.low:
            findings.append(ImportFinding(index=m.index, date=m.date, time=m.time, sender=m.sender,
                                          text=m.text[:_SNIPPET], evidence=ev))

    by_attachment = {a.strip().lower(): m for m in export.messages for a in m.attachments}
    images_checked = 0
    for name, data in export.images.items():
        try:
            qr = await run_in_threadpool(decode_qr_codes, data, max_pixels=settings.max_image_pixels,
                                         max_codes=settings.max_qr_codes_per_image)
        except ImageRejected:
            continue
        images_checked += 1
        if not qr.codes:
            continue
        ev = await analyzer.analyze_qr(qr, InputType.image, budget)
        m = by_attachment.get(name.lower())
        findings.append(ImportFinding(index=m.index if m else -1, date=m.date if m else "", time=m.time if m else "",
                                      sender=m.sender if m else "", text=f"QR code in {name}", attachment=name,
                                      evidence=ev))
    if export.skipped_images:
        warnings.append(f"{export.skipped_images} more photos were not scanned (limit {len(export.images)}).")

    findings.sort(key=lambda f: ({"High": 0, "Medium": 1, "Low": 2}[f.evidence.risk_level.value], f.index))
    level = aggregate.worst(*(f.evidence.risk_level for f in findings)) if findings else RiskLevel.low
    return ImportReport(
        title=export.title, risk_level=level, messages_total=len(export.messages),
        messages_checked=len(candidates), links_found=len(keys), links_checked=len(to_fetch),
        images_checked=images_checked, findings=findings, warnings=warnings,
    )


@router.post("/import/chat", response_model=ImportReport)
async def import_chat(request: Request, file: UploadFile = File(...)) -> ImportReport:
    try:
        data = await file.read(settings.max_import_bytes + 1)
        if len(data) > settings.max_import_bytes:
            raise HTTPException(413, f"File too large (max {settings.max_import_bytes // (1024 * 1024)} MB).")
        try:
            export = await run_in_threadpool(load_export, file.filename or "", data)
        except ExportRejected as e:
            raise HTTPException(415, str(e)) from None
    finally:
        await file.close()  # deletes any spooled temp file
        data = b""
    return await analyze_export(request.app.state.analyzer, export)


# --- live WhatsApp (bridge) -----------------------------------------------------


async def _bridge(method: str, path: str, json: dict | None = None, timeout: float = 10.0) -> dict:
    async with httpx.AsyncClient(base_url=settings.whatsapp_bridge_url, timeout=timeout, trust_env=False) as c:
        r = await c.request(method, path, json=json)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json().get("detail", "bridge error"))
    return r.json()


@router.get("/whatsapp/status")
async def whatsapp_status() -> dict:
    try:
        st = await _bridge("GET", "/status", timeout=3.0)
    except (httpx.HTTPError, ValueError):
        return {"enabled": False}
    return {"enabled": True, **st, "alerts": len(_alerts), "checked_total": _stats["checked"]}


@router.post("/whatsapp/link")
async def whatsapp_link() -> dict:
    return await _bridge("POST", "/link", timeout=30.0)


@router.post("/whatsapp/logout")
async def whatsapp_logout() -> dict:
    _alerts.clear()
    return await _bridge("POST", "/logout", timeout=15.0)


@router.get("/whatsapp/chats")
async def whatsapp_chats() -> dict:
    return await _bridge("GET", "/chats")


@router.post("/whatsapp/chats")
async def whatsapp_add_chat(body: dict) -> dict:
    """Add (and select) a chat by phone number, for chats WhatsApp never listed."""
    return await _bridge("POST", "/chats", json={"number": str(body.get("number", ""))[:32]})


@router.put("/whatsapp/selection")
async def whatsapp_selection(body: dict) -> dict:
    """{mode: "unknown"|"manual", include: [...], exclude: [...]} (or the older {chat_ids})."""
    if "chat_ids" in body:
        return await _bridge("PUT", "/selection", json={"chat_ids": list(body.get("chat_ids") or [])})
    payload = {"mode": body.get("mode", "unknown"),
               "include": list(body.get("include") or []), "exclude": list(body.get("exclude") or [])}
    return await _bridge("PUT", "/selection", json=payload)


@router.get("/whatsapp/alerts", response_model=list[WhatsAppAlert])
async def whatsapp_alerts() -> list[WhatsAppAlert]:
    return list(reversed(_alerts))


@router.delete("/whatsapp/alerts")
async def whatsapp_clear_alerts() -> dict:
    _alerts.clear()
    return {"cleared": True}


def call_evidence(chat_id: str, video: bool = False) -> Evidence:
    """An unknown number called on WhatsApp. Foreign numbers are a classic scam opener."""
    digits = chat_id.split("@")[0]
    number = f"+{digits}" if digits.isdigit() else "a hidden number"
    foreign = digits.isdigit() and not digits.startswith("961")
    what = "video call" if video else "call"
    sig = Signal(
        id="unknown_caller",
        title=f"Unknown {'foreign ' if foreign else ''}number {what}ed you on WhatsApp",
        detail=(f"{number} is not in your contacts. "
                + ("Scam calls often come from foreign numbers posing as banks, couriers or WhatsApp support. "
                   if foreign else "")
                + "Never share codes or send money to someone you don't know; hang up and call the official number."),
        severity=Severity.medium if foreign else Severity.low,
        label=EvidenceLabel.automated_indicator, source="amaan",
    )
    level = RiskLevel.medium if foreign else RiskLevel.low
    return Evidence(input_type=InputType.text, analyzed_at=datetime.now(timezone.utc), items=[], signals=[sig],
                    risk_level=level, complete=True, explanation=sig.detail, warnings=[], stats={})


@router.post("/whatsapp/ingest")
async def whatsapp_ingest(
    request: Request,
    kind: str = Form(...),
    chat_id: str = Form(""),
    chat_name: str = Form(""),
    sender: str = Form(""),
    timestamp: int = Form(0),
    text: str = Form(""),
    file: UploadFile | None = File(None),
    x_bridge_token: str = Header(""),
) -> dict:
    """Called by the bridge for each new message in a selected chat."""
    if not settings.bridge_token:
        raise HTTPException(503, "WhatsApp bridge token not configured.")
    if not secrets.compare_digest(x_bridge_token, settings.bridge_token):
        raise HTTPException(403, "Invalid bridge token.")
    analyzer: Analyzer = request.app.state.analyzer
    _stats["checked"] += 1
    if kind in ("call", "video_call"):
        ev = call_evidence(chat_id, video=kind == "video_call")
        _alerts.append(WhatsAppAlert(
            id=next(_alert_ids), received_at=datetime.fromtimestamp(timestamp, timezone.utc) if timestamp
            else datetime.now(timezone.utc), chat_name=chat_name or chat_id, sender=sender, kind=kind, text="", evidence=ev))
        return {"stored": True, "risk_level": ev.risk_level.value}

    evidences: list[Evidence] = []
    try:
        if file is not None:
            data = await file.read(settings.max_upload_bytes + 1)
            if len(data) <= settings.max_upload_bytes:
                try:
                    qr = await run_in_threadpool(decode_qr_codes, data, max_pixels=settings.max_image_pixels,
                                                 max_codes=settings.max_qr_codes_per_image)
                    if qr.codes:
                        evidences.append(await analyzer.analyze_qr(qr, InputType.image))
                except ImageRejected:
                    pass
            data = b""
    finally:
        if file is not None:
            await file.close()
    if text.strip():
        evidences.append(await analyzer.analyze_text(TextRequest(text=text)))

    flagged = [e for e in evidences if e.risk_level is not RiskLevel.low]
    if not flagged:
        return {"stored": False}
    ev = max(flagged, key=lambda e: {"High": 2, "Medium": 1, "Low": 0}[e.risk_level.value])
    _alerts.append(WhatsAppAlert(
        id=next(_alert_ids),
        received_at=datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else datetime.now(timezone.utc),
        chat_name=chat_name or chat_id, sender=sender, kind=kind,
        text=text[:_SNIPPET], evidence=ev,
    ))
    return {"stored": True, "risk_level": ev.risk_level.value}
