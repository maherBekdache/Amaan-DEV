"""Orchestrates one analysis: extract items -> local checks -> URL.vet -> verdict."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from amaan.clients.urlvet import UrlVetClient
from amaan.config import Settings
from amaan.extract.html import parse_html
from amaan.extract.payloads import classify_payload
from amaan.extract.qr import QRResult
from amaan.extract.urls import ExtractedUrl, TextFlags, defang, extract_urls, parse_candidate
from amaan.schemas import (
    AnalyzedItem, Evidence, InputType, ItemKind, ItemSource, RiskLevel, Signal, TextRequest,
    UrlVetResult, UrlVetStatus,
)
from amaan.scoring import aggregate, local_rules, text_cues


@dataclass
class _Pending:
    kind: ItemKind
    source: ItemSource
    display: str
    host: str | None = None
    host_ascii: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    check_url: str | None = None
    signals: list[Signal] = field(default_factory=list)
    urlvet: UrlVetResult | None = None


def _url_pending(u: ExtractedUrl, source: ItemSource) -> _Pending:
    return _Pending(
        kind=ItemKind.url, source=source, display=defang(u.url), host=u.host, host_ascii=u.host_ascii,
        check_url=u.url, signals=local_rules.url_signals(u),
    )


@dataclass
class LinkBudget:
    """How many new links may still go to URL.vet, plus results already fetched."""

    limit: int
    remaining: int = -1
    cache: dict[str, UrlVetResult] = field(default_factory=dict)
    queued: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.remaining < 0:
            self.remaining = self.limit


def _key(url: str) -> str:
    return url.lower().split("://", 1)[-1].rstrip("/")


class Analyzer:
    def __init__(self, settings: Settings, urlvet: UrlVetClient) -> None:
        self.s = settings
        self.urlvet = urlvet

    async def _check_urls(self, pending: list[_Pending], warnings: list[str],
                          budget: "LinkBudget | None" = None) -> int:
        """Send links to URL.vet, at most `budget.remaining` new ones (URL.vet allows
        20 checks a minute). A shared budget lets one chat import check each link once."""
        budget = budget or LinkBudget(self.s.max_urls_per_request)
        to_send: list[_Pending] = []
        skipped = 0
        for p in (p for p in pending if p.check_url):
            k = _key(p.check_url)
            if k in budget.cache:
                p.urlvet = budget.cache[k].model_copy()
            elif k in budget.queued or budget.remaining > 0:
                if k not in budget.queued:
                    budget.queued.add(k)
                    budget.remaining -= 1
                to_send.append(p)
            else:
                skipped += 1
                p.urlvet = UrlVetResult(status=UrlVetStatus.skipped,
                                        message=f"Not checked: limit of {budget.limit} links per check reached.")
        if skipped:
            warnings.append(f"{skipped} link(s) were not sent to URL.vet (limit {budget.limit} per check).")
        t0 = time.perf_counter()
        unique: dict[str, _Pending] = {}
        for p in to_send:
            unique.setdefault(_key(p.check_url), p)
        results = await asyncio.gather(*(self.urlvet.analyze(p.check_url) for p in unique.values()))
        for k, r in zip(unique.keys(), results):
            budget.cache[k] = r
            budget.queued.discard(k)
        for p in to_send:
            p.urlvet = budget.cache[_key(p.check_url)].model_copy()
        return int((time.perf_counter() - t0) * 1000)

    def _finish(self, input_type: InputType, pending: list[_Pending], message_signals: list[Signal],
                warnings: list[str], stats: dict, input_desc: str) -> Evidence:
        items: list[AnalyzedItem] = []
        for idx, p in enumerate(pending, start=1):
            signals = list(p.signals)
            if p.urlvet:
                signals = aggregate.urlvet_signals(p.urlvet) + signals
            level = aggregate.item_level(p.kind, signals, p.urlvet)
            item = AnalyzedItem(
                id=idx, kind=p.kind, source=p.source, display=p.display, host=p.host, host_ascii=p.host_ascii,
                details=p.details, urlvet=p.urlvet, signals=signals, risk_level=level, summary="",
            )
            item.summary = aggregate.item_summary(item)
            items.append(item)

        level = aggregate.overall_level(items, message_signals)
        complete = all(
            i.urlvet is None or i.urlvet.status in (UrlVetStatus.ok, UrlVetStatus.skipped) or i.kind is not ItemKind.url
            for i in items
        ) and not any(i.urlvet and i.urlvet.incomplete for i in items)
        problems = {i.urlvet.status for i in items if i.urlvet and i.urlvet.status not in
                    (UrlVetStatus.ok, UrlVetStatus.skipped)}
        if any(i.urlvet and i.urlvet.mock for i in items):
            warnings.insert(0, "MOCK URL.vet is running: link verdicts are FAKE (development only).")
        if UrlVetStatus.unavailable in problems:
            warnings.append("URL.vet is not running, so links were only checked with Amaan's local rules.")
        elif UrlVetStatus.timeout in problems:
            warnings.append("URL.vet took too long for some links.")
        elif UrlVetStatus.rate_limited in problems:
            warnings.append("URL.vet's rate limit was reached; try again in a minute.")

        return Evidence(
            input_type=input_type,
            analyzed_at=datetime.now(timezone.utc),
            items=items,
            signals=message_signals,
            risk_level=level,
            complete=complete,
            explanation=aggregate.explain(items, message_signals, level, complete, input_desc),
            warnings=warnings,
            stats=stats,
        )

    # --- text ------------------------------------------------------------------

    async def analyze_text(self, req: TextRequest, budget: LinkBudget | None = None) -> Evidence:
        t0 = time.perf_counter()
        warnings: list[str] = []
        text = req.text or ""
        if len(text) > self.s.max_text_chars:
            warnings.append(f"Text was longer than {self.s.max_text_chars} characters; only the start was analyzed.")
            text = text[: self.s.max_text_chars]

        pending: list[_Pending] = []
        flags = TextFlags()

        by_key: dict[str, _Pending] = {}
        decoys: set[str] = set()  # link labels that point somewhere else

        def add(p: _Pending) -> None:
            k = _key(p.check_url or p.display)
            if k in by_key:  # same link from another flavour: keep every signal
                existing = by_key[k]
                known = {s.id for s in existing.signals}
                existing.signals = [s for s in p.signals if s.id not in known] + existing.signals
                return
            by_key[k] = p
            pending.append(p)

        # 1) Dropped HTML: real link targets, plus a check that the visible text matches.
        if req.html:
            content = parse_html(req.html)
            for link in content.links[:50]:
                u = parse_candidate(link.href)
                if not u:
                    continue
                p = _url_pending(u, ItemSource.html_link)
                mismatch = local_rules.link_text_mismatch(u.registrable, link.text)
                if mismatch:
                    p.signals.insert(0, mismatch)
                    for shown in extract_urls(link.text, limit=3).urls:
                        decoys.add(_key(shown.url))
                add(p)
            if not text.strip():
                text = content.text[: self.s.max_text_chars]

        # 2) Dropped links (text/uri-list): one URL per line, '#' lines are comments.
        for line in (req.uri_list or "").splitlines()[:50]:
            line = line.strip()
            if line and not line.startswith("#"):
                u = parse_candidate(line)
                if u:
                    add(_url_pending(u, ItemSource.uri_list))

        # 3) Plain text.
        extraction = extract_urls(text, limit=50)
        flags = extraction.flags
        for u in extraction.urls:
            if _key(u.url) not in decoys:  # the visible label of a deceptive link is not a destination
                add(_url_pending(u, ItemSource.text))

        message_signals = local_rules.text_flag_signals(flags) + text_cues.text_cue_signals(extraction.cleaned_text)
        urlvet_ms = await self._check_urls(pending, warnings, budget)
        stats = {"links_found": sum(1 for p in pending if p.kind is ItemKind.url), "urlvet_ms": urlvet_ms,
                 "total_ms": int((time.perf_counter() - t0) * 1000)}
        return self._finish(InputType.text, pending, message_signals, warnings, stats, "text")

    # --- image / camera --------------------------------------------------------

    async def analyze_qr(self, qr: QRResult, input_type: InputType,
                         budget: LinkBudget | None = None) -> Evidence:
        t0 = time.perf_counter()
        warnings: list[str] = []
        pending: list[_Pending] = []
        seen: set[str] = set()

        for code in qr.codes:
            payload = classify_payload(code.text)
            if payload.kind is ItemKind.url:
                u = parse_candidate(payload.raw)
                if u and _key(u.url) not in seen:
                    seen.add(_key(u.url))
                    pending.append(_url_pending(u, ItemSource.qr))
                elif not u:
                    pending.append(_Pending(kind=ItemKind.text, source=ItemSource.qr, display=payload.raw[:200],
                                            details={"note": "Looks like a link but is not a valid address"}))
                continue

            embedded = extract_urls(payload.raw, limit=10).urls if payload.kind is ItemKind.text else []
            for u in embedded:
                if _key(u.url) not in seen:
                    seen.add(_key(u.url))
                    pending.append(_url_pending(u, ItemSource.qr))
            if embedded and not payload.details:
                continue  # plain text whose only content is links
            display = defang(payload.raw[:200]) if payload.kind is ItemKind.text else payload.raw[:200]
            if payload.kind is ItemKind.wifi:
                display = f"Wi-Fi network “{payload.details.get('ssid', '')}”"
            pending.append(_Pending(kind=payload.kind, source=ItemSource.qr, display=display,
                                    details=payload.details, signals=local_rules.payload_signals(payload)))

        if not qr.codes:
            warnings.append("No QR code was found in this image. Reading text from screenshots is not supported yet.")
        if len(qr.codes) >= self.s.max_qr_codes_per_image:
            warnings.append(f"Only the first {self.s.max_qr_codes_per_image} QR codes were analyzed.")

        urlvet_ms = await self._check_urls(pending, warnings, budget)
        stats = {"qr_codes": len(qr.codes), "image": f"{qr.width}x{qr.height} {qr.format}",
                 "decode_ms": qr.elapsed_ms, "urlvet_ms": urlvet_ms,
                 "decoders": ",".join(sorted({d for c in qr.codes for d in c.decoders})) or "none",
                 "total_ms": int((time.perf_counter() - t0) * 1000) + qr.elapsed_ms}
        desc = "camera frame" if input_type is InputType.camera else "image"
        return self._finish(input_type, pending, [], warnings, stats, desc)
