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
from amaan.extract.urls import ExtractedUrl, defang, extract_urls, parse_candidate
from amaan.lookups import lookup_links
from amaan.reputation.base import SourceResult
from amaan.schemas import (
    AnalyzedItem, Evidence, InputType, ItemKind, ItemSource, Signal, TextRequest, UrlVetResult, UrlVetStatus,
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
    sources: list[SourceResult] = field(default_factory=list)


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
    sources: dict[str, list[SourceResult]] = field(default_factory=dict)
    queued: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.remaining < 0:
            self.remaining = self.limit


def link_key(url: str) -> str:
    """Same link regardless of scheme, case or a trailing slash."""
    return url.lower().split("://", 1)[-1].rstrip("/")


async def _no_sources() -> list[SourceResult]:
    return []


class Analyzer:
    def __init__(self, settings: Settings, urlvet: UrlVetClient, reputation=None) -> None:
        self.s = settings
        self.urlvet = urlvet
        self.reputation = reputation  # amaan.reputation.aggregator.Reputation (optional)

    async def _check_urls(self, pending: list[_Pending], warnings: list[str],
                          budget: LinkBudget | None = None) -> int:
        """Send links to URL.vet, at most `budget.remaining` new ones (URL.vet allows
        20 checks a minute). A shared budget lets one chat import check each link once."""
        budget = budget or LinkBudget(self.s.max_urls_per_request)
        to_send: list[_Pending] = []
        skipped = 0
        for p in (p for p in pending if p.check_url):
            k = link_key(p.check_url)
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
            unique.setdefault(link_key(p.check_url), p)

        # URL.vet and every reputation source run at the same time.
        results, source_lists = await asyncio.gather(
            asyncio.gather(*(self.urlvet.analyze(p.check_url) for p in unique.values())),
            asyncio.gather(*((self.reputation.check(p.check_url) if self.reputation else _no_sources())
                             for p in unique.values())),
        )
        for k, r, srcs in zip(unique.keys(), results, source_lists):
            budget.cache[k] = r
            budget.sources[k] = srcs
            budget.queued.discard(k)
        for p in to_send:
            p.urlvet = budget.cache[link_key(p.check_url)].model_copy()
        for p in pending:
            if p.check_url and link_key(p.check_url) in budget.sources:
                p.sources = budget.sources[link_key(p.check_url)]
        return int((time.perf_counter() - t0) * 1000)

    def _finish(self, input_type: InputType, pending: list[_Pending], message_signals: list[Signal],
                warnings: list[str], stats: dict, input_desc: str) -> Evidence:
        items: list[AnalyzedItem] = []
        for idx, p in enumerate(pending, start=1):
            signals = list(p.signals)
            if p.urlvet:
                signals = aggregate.urlvet_signals(p.urlvet) + signals
            signals = aggregate.source_signals(p.sources) + signals
            level = aggregate.item_level(p.kind, signals, p.urlvet)
            item = AnalyzedItem(
                id=idx, kind=p.kind, source=p.source, display=p.display, host=p.host, host_ascii=p.host_ascii,
                details=p.details, urlvet=p.urlvet, sources=p.sources, signals=signals, risk_level=level, summary="",
                lookups=lookup_links(p.check_url, p.host_ascii) if p.kind is ItemKind.url and p.check_url and p.host_ascii else [],
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

    # --- links only (hybrid mobile mode) ----------------------------------------

    async def analyze_links(self, urls: list[str]) -> Evidence:
        """The phone found these links itself; only the links are sent here."""
        return await self.analyze_text(TextRequest(uri_list="\n".join(u.strip() for u in urls if u.strip())))

    # --- text ------------------------------------------------------------------

    async def analyze_text(self, req: TextRequest, budget: LinkBudget | None = None) -> Evidence:
        t0 = time.perf_counter()
        warnings: list[str] = []
        text = req.text or ""
        if len(text) > self.s.max_text_chars:
            warnings.append(f"Text was longer than {self.s.max_text_chars} characters; only the start was analyzed.")
            text = text[: self.s.max_text_chars]

        pending: list[_Pending] = []
        by_key: dict[str, _Pending] = {}
        decoys: set[str] = set()  # link labels that point somewhere else

        def add(p: _Pending) -> None:
            k = link_key(p.check_url or p.display)
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
                        decoys.add(link_key(shown.url))
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
        for u in extraction.urls:
            if link_key(u.url) not in decoys:  # the visible label of a deceptive link is not a destination
                add(_url_pending(u, ItemSource.text))

        message_signals = local_rules.text_flag_signals(extraction.flags) + text_cues.text_cue_signals(
            extraction.cleaned_text, has_link=any(p.kind is ItemKind.url for p in pending))
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
                if u and link_key(u.url) not in seen:
                    seen.add(link_key(u.url))
                    pending.append(_url_pending(u, ItemSource.qr))
                elif not u:
                    pending.append(_Pending(kind=ItemKind.text, source=ItemSource.qr, display=payload.raw[:200],
                                            details={"note": "Looks like a link but is not a valid address"}))
                continue

            embedded = extract_urls(payload.raw, limit=10).urls if payload.kind is ItemKind.text else []
            for u in embedded:
                if link_key(u.url) not in seen:
                    seen.add(link_key(u.url))
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
