"""Turn signals into Low / Medium / High, and explain why in plain English.

Rules (kept simple so they can be explained in the report):
- An item takes the level of its worst signal (high -> High, medium -> Medium).
- URL.vet's verdict maps Risky -> High, Suspicious -> Medium, Safe -> Low.
- A threat-list hit (community report) is always High.
- A link URL.vet could not check is at least Medium, unless it is on our
  verified official-domain list: "not checked" must never look like "safe".
- The overall level is the worst item or message-level signal.
- Escalation: a link with its own warning sign (not just "unchecked") inside
  a message showing two or more scam patterns is High.
"""

from __future__ import annotations

from amaan.extract.urls import parse_candidate
from amaan.reputation.base import SourceResult, SourceStatus, SourceVerdict
from amaan.schemas import (
    AnalyzedItem,
    EvidenceLabel,
    Expansion,
    ItemKind,
    RiskLevel,
    Severity,
    Signal,
    UrlVetResult,
    UrlVetStatus,
)
from amaan.scoring import local_rules

_ORDER = {RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}
_SEV = {Severity.high: RiskLevel.high, Severity.medium: RiskLevel.medium}
_VERDICT = {"risky": RiskLevel.high, "suspicious": RiskLevel.medium, "safe": RiskLevel.low}


def worst(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=_ORDER.__getitem__, default=RiskLevel.low)


def rank(level: RiskLevel) -> int:
    """0 = Low, 1 = Medium, 2 = High (for sorting)."""
    return _ORDER[level]


def urlvet_signals(r: UrlVetResult) -> list[Signal]:
    """Expose URL.vet's findings as labelled signals too."""
    out: list[Signal] = []
    if r.status is not UrlVetStatus.ok:
        out.append(Signal(
            id="link_not_checked", title="Link couldn't be checked in the sandbox",
            detail=f"{r.message} Until it is checked, treat it as unknown: don't log in or pay there.",
            severity=Severity.low, label=EvidenceLabel.automated_indicator, source="urlvet",
        ))
        return out
    if r.threat_listed:
        out.append(Signal(
            id="threat_list", title="Reported as phishing or malware",
            detail="Listed by: " + (", ".join(r.threat_sources) or "a threat list") + ".",
            severity=Severity.high, label=EvidenceLabel.community_report, source="urlvet",
        ))
    level = _VERDICT.get((r.verdict or "").lower())
    if level:
        sev = {RiskLevel.high: Severity.high, RiskLevel.medium: Severity.medium, RiskLevel.low: Severity.good}[level]
        out.append(Signal(
            id="urlvet_verdict",
            title=f"{'MOCK (fake) ' if r.mock else ''}URL.vet verdict: {r.verdict} ({r.final_score}/100)",
            detail="; ".join(r.bad_reasons[:3]) or "; ".join(r.good_reasons[:2]),
            severity=sev, label=EvidenceLabel.automated_indicator, source="urlvet",
        ))
    return out


_PROGRAM_TYPES = {
    "application/vnd.android.package-archive", "application/x-msdownload", "application/x-msdos-program",
    "application/x-msi", "application/x-dosexec", "application/x-executable", "application/x-sh",
    "application/java-archive", "application/x-apple-diskimage", "application/x-ms-installer",
}
_PROGRAM_ENDINGS = (".apk", ".xapk", ".apks", ".exe", ".msi", ".scr", ".bat", ".cmd", ".ps1", ".vbs", ".jar",
                    ".dmg", ".pkg", ".sh")


def _exp(id: str, title: str, detail: str, severity: Severity) -> Signal:
    return Signal(id=id, title=title, detail=detail, severity=severity,
                  label=EvidenceLabel.automated_indicator, source="expander")


def expansion_signals(exp: Expansion | None, start_url: str | None) -> list[Signal]:
    """What the expansion worker saw when it followed the link (sandbox layer L5)."""
    if exp is None or exp.status != "ok":
        return []
    start = parse_candidate(start_url) if start_url else None
    seen = {start.registrable} if start else set()
    out: list[Signal] = []
    # Every new site on the way gets Amaan's link rules too: the scam is often only at the end.
    for raw in exp.raw_hops[1:]:
        u = parse_candidate(raw)
        if not u or u.registrable in seen:
            continue
        seen.add(u.registrable)
        for s in local_rules.url_signals(u):
            if s.severity in (Severity.high, Severity.medium) and s.id != "hidden_redirect":
                out.append(s.model_copy(update={"id": f"redirect_{s.id}", "title": f"After a redirect: {s.title}",
                                                "source": "expander"}))
    final = parse_candidate(exp.raw_hops[-1]) if exp.raw_hops else None
    moved = sum(1 for h in exp.hops if h.via)
    if moved and final and start and final.registrable != start.registrable:
        out.append(_exp("redirects_elsewhere", f"Leads to {final.host} after {moved} redirect{'s' if moved > 1 else ''}",
                        "Amaan's sandbox followed the link without opening it on your device.", Severity.info))
    if exp.stopped == "blocked address":
        out.append(_exp("redirects_private", "Link tries to reach a private network address",
                        "It points to an address inside a home or company network (for example a router). "
                        "Amaan's sandbox refused to go there.", Severity.medium))
    official = bool(final and final.registrable in local_rules.official_domains())
    if not official:
        if "code" in exp.asks_for:
            out.append(_exp("page_asks_code", "The page asks for a verification code",
                            "Real companies never ask for the code they send you by SMS or WhatsApp. "
                            "Giving it lets scammers take over your account.", Severity.high))
        if "password" in exp.asks_for:
            out.append(_exp("page_asks_password", "The page asks for a password",
                            "Only type a password on a site you opened yourself, not from a link.", Severity.medium))
        if "card" in exp.asks_for:
            out.append(_exp("page_asks_card", "The page asks for card details",
                            "Scam pages copy payment forms to steal card numbers.", Severity.medium))
    if exp.human_check:
        out.append(_exp("page_human_check", "The page hides behind a 'verify you are human' check",
                        "Scam pages use these checks to hide from security scanners, so Amaan could not see "
                        "what comes after it. Treat it as unknown.", Severity.medium))
    d = exp.download
    if d:
        name = d.filename.lower()
        program = d.content_type in _PROGRAM_TYPES or name.endswith(_PROGRAM_ENDINGS)
        if d.content_type == "application/vnd.android.package-archive" or name.endswith((".apk", ".xapk", ".apks")):
            out.append(_exp("downloads_app", "Link downloads an Android app (APK)",
                            "Apps from links can steal SMS codes and banking details. Install apps only from "
                            f"Google Play. File fingerprint (SHA-256): {d.sha256[:16]}...", Severity.high))
        elif program:
            out.append(_exp("downloads_program", "Link downloads a program",
                            f"Running files from links can install malware. Fingerprint: {d.sha256[:16]}...",
                            Severity.high))
        else:
            out.append(_exp("downloads_file", f"Link downloads a file ({d.content_type or 'unknown type'})",
                            "Amaan did not open it. Open files only from senders you know.", Severity.medium))
    return out


def source_signals(sources: list[SourceResult]) -> list[Signal]:
    """Turn the multi-source answers into labelled reasons."""
    out: list[Signal] = []
    checked = [r for r in sources if r.status is SourceStatus.ok]
    for r in checked:
        sid = f"source_{r.source.lower().replace(' ', '_').replace('.', '')}"
        if r.verdict is SourceVerdict.malicious:
            out.append(Signal(
                id=sid,
                title=(f"Reported as dangerous by {r.source}" if r.community else f"{r.source} flags it as dangerous"),
                detail=r.detail, severity=Severity.high,
                label=EvidenceLabel.community_report if r.community else EvidenceLabel.automated_indicator,
                source=r.source,
            ))
        elif r.verdict is SourceVerdict.suspicious:
            out.append(Signal(
                id=sid, title=f"{r.source} finds it suspicious",
                detail=r.detail, severity=Severity.medium, label=EvidenceLabel.automated_indicator, source=r.source,
            ))
    clean = [r.source for r in checked if r.verdict is SourceVerdict.clean]
    if clean and not out:
        out.append(Signal(
            id="sources_clean", title=f"No warnings from {len(clean)} security source{'s' if len(clean) > 1 else ''}",
            detail="Checked: " + ", ".join(clean) + ". A new scam site may not be listed yet.",
            severity=Severity.good, label=EvidenceLabel.automated_indicator, source="amaan",
        ))
    return out


def item_level(kind: ItemKind, signals: list[Signal], urlvet: UrlVetResult | None) -> RiskLevel:
    level = worst(*(_SEV[s.severity] for s in signals if s.severity in _SEV))
    if urlvet is not None and urlvet.status is UrlVetStatus.ok:
        level = worst(level, _VERDICT.get((urlvet.verdict or "").lower(), RiskLevel.medium))
    elif kind is ItemKind.url:
        verified = any(s.label is EvidenceLabel.verified for s in signals)
        if not verified:
            level = worst(level, RiskLevel.medium)
    return level


def overall_level(items: list[AnalyzedItem], message_signals: list[Signal]) -> RiskLevel:
    msg_levels = [_SEV[s.severity] for s in message_signals if s.severity in _SEV]
    level = worst(*(i.risk_level for i in items), *msg_levels)
    cues = [s for s in message_signals if s.id.startswith("cue_")]
    flagged_link = any(
        s.severity in (Severity.medium, Severity.high)
        for i in items if i.kind is ItemKind.url for s in i.signals
    )
    if len(cues) >= 2 and flagged_link:
        level = RiskLevel.high
    return level


def item_summary(item: AnalyzedItem) -> str:
    bad = [s for s in item.signals if s.severity in (Severity.high, Severity.medium)]
    if bad:
        return bad[0].title
    if item.urlvet and item.urlvet.status is UrlVetStatus.ok:
        return f"URL.vet rated it {item.urlvet.verdict} ({item.urlvet.final_score}/100)."
    if item.urlvet and item.urlvet.status is not UrlVetStatus.skipped:
        return f"Not checked: {item.urlvet.message}"
    infos = [s for s in item.signals if s.severity in (Severity.info, Severity.low, Severity.good)]
    return infos[0].title if infos else "No warning signs found."


_ADVICE = {
    RiskLevel.high: "Do not open it, do not scan it with your phone, and never share codes, passwords or card details.",
    RiskLevel.medium: "Be careful: confirm with the sender through another channel before opening anything or paying.",
    RiskLevel.low: "No strong warning signs, but stay alert: never share verification codes.",
}


def explain(items: list[AnalyzedItem], message_signals: list[Signal], level: RiskLevel,
            complete: bool, input_desc: str) -> str:
    parts: list[str] = []
    links = [i for i in items if i.kind is ItemKind.url]
    if not items:
        parts.append(f"No links or QR codes were found in this {input_desc}.")
    else:
        flagged = [i for i in items if i.risk_level is not RiskLevel.low]
        noun = "item" if len(items) == 1 else "items"
        if flagged:
            top = max(flagged, key=lambda i: _ORDER[i.risk_level])
            parts.append(f"{level.value} risk: {len(flagged)} of {len(items)} {noun} "
                         f"{'needs' if len(flagged) == 1 else 'need'} attention. "
                         f"{top.display}: {top.summary.rstrip('.')}.")
        else:
            parts.append(f"Low risk: checked {len(items)} {noun} ({len(links)} link{'s' if len(links) != 1 else ''}) "
                         "and found no warning signs.")
    cue_hits = [s for s in message_signals if s.id.startswith("cue_") and s.id != "cue_scam_script"]
    if cue_hits:
        parts.append("The message itself shows scam patterns: " + ", ".join(s.title.lower() for s in cue_hits) + ".")
    other = [s for s in message_signals if not s.id.startswith("cue_") and s.severity in (Severity.high, Severity.medium)]
    if other:
        parts.append(other[0].title + ".")
    if not complete:
        parts.append("Some checks could not run, so this result is incomplete.")
    labels = {s.label for i in items for s in i.signals} | {s.label for s in message_signals}
    if EvidenceLabel.community_report in labels:
        parts.append("At least one link has been reported by others as malicious.")
    elif level is not RiskLevel.low:
        parts.append("These are automated indicators, not a confirmed report.")
    parts.append(_ADVICE[level])
    return " ".join(parts)
