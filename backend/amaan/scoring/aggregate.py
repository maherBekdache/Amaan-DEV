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

from amaan.schemas import (
    AnalyzedItem, EvidenceLabel, ItemKind, RiskLevel, Severity, Signal, UrlVetResult, UrlVetStatus,
)

_ORDER = {RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}
_SEV = {Severity.high: RiskLevel.high, Severity.medium: RiskLevel.medium}
_VERDICT = {"risky": RiskLevel.high, "suspicious": RiskLevel.medium, "safe": RiskLevel.low}


def worst(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=lambda l: _ORDER[l], default=RiskLevel.low)


def urlvet_signals(r: UrlVetResult) -> list[Signal]:
    """Expose URL.vet's findings as labelled signals too."""
    out: list[Signal] = []
    if r.status is not UrlVetStatus.ok:
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
            id="urlvet_verdict", title=f"URL.vet verdict: {r.verdict} ({r.final_score}/100)",
            detail="; ".join(r.bad_reasons[:3]) or "; ".join(r.good_reasons[:2]),
            severity=sev, label=EvidenceLabel.automated_indicator, source="urlvet",
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
    cue_hits = [s for s in message_signals if s.id.startswith("cue_")]
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
