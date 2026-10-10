"""Keyword cues for common Lebanese scam scripts (English, Arabic, Arabizi).

This is a deliberately simple, transparent placeholder for the future
scam-intent model: each cue says exactly which phrase matched. Cues alone
never push a message above Medium.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from amaan.schemas import EvidenceLabel, Severity, Signal

_AR_DIACRITICS = re.compile(r"[ً-ٰٟـ]")


def normalize_arabic(text: str) -> str:
    text = _AR_DIACRITICS.sub("", text)
    return (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            .replace("ة", "ه").replace("ى", "ي"))


@dataclass(frozen=True)
class Cue:
    id: str
    title: str
    why: str
    patterns: tuple[str, ...]


CUES: tuple[Cue, ...] = (
    Cue("asks_for_code", "Asks you to share a code",
        "Banks, OMT, Whish and WhatsApp never ask you to send a verification code. Sharing it gives away your account.",
        (r"\b(otp|verification code|security code|pin code|6[- ]?digit code)\b",
         r"\b(send|forward|give)( me)? (the |your )?code\b",
         r"رمز (التحقق|التاكيد|الامان)", r"(ابعت|ابعتلي|ارسل|ارسلي|بعتلي)\s*(لي\s*)?(ال)?(كود|رمز)",
         r"\b(ab3at|ba3atli|b3atli|ab3atli|ba3etli|eb3atli)\w*\s+(el\s*|l\s*)?code\b",
         r"\bcode (el )?(ta2kid|ta2keed|t2kid)\b")),
    Cue("urgency_threat", "Pressure or threat",
        "Scams create urgency (account blocked, last chance) so you act before thinking.",
        (r"\b(urgent|immediately|within 24 hours|account (will be )?(suspended|blocked|closed|locked)|last (chance|warning))\b",
         r"(عاجل|فورا|خلال 24 ساعه|سيتم (ايقاف|اغلاق|حظر|تعليق)|حسابك (موقوف|مقفل|محظور))",
         r"\b(ra7 yitsaker|ra7 ysakro|7sebak|hsebak|ysakkro)\b")),
    Cue("prize", "Prize, gift or lottery",
        "Unexpected prizes that need a fee, a code or your details are a classic scam.",
        (r"\b(you('ve)? won|winner|congratulations|claim your (prize|reward|gift)|free (gift|iphone))\b",
         r"(ربحت|فزت|مبروك|جايزه|جائزه|هديه مجانيه|سحب)",
         r"\b(rbe7t|rbi7t|reb7et|mabrouk|mabrook|jeyze|ja2ize|jayze|hdiye)\b")),
    Cue("money_request", "Asks for money or a transfer",
        "Requests to transfer money, pay a 'fee' or top up a number are the end goal of most scams.",
        (r"\b(transfer|send money|wire|pay (a )?fee|top[- ]?up|recharge|usdt|bitcoin|crypto)\b",
         r"(حول|حولي|حوللي|تحويل|ابعتلي مصاري|رسوم|اشحن|تشريج|دولار فريش)",
         r"\b(7awel|7awwel|7awelli|7aweli|ba3atli masari|ab3atli masari|cha7en|sha7en|fresh dollar)\w*\b")),
    Cue("delivery_lure", "Parcel or delivery pretext",
        "Fake 'your parcel is waiting' messages lead to payment or login pages.",
        (r"\b(parcel|package|shipment|delivery|customs fee|track(ing)? your)\b",
         r"(طرد|شحنه|توصيل|جمرك|رسوم الجمارك)",
         r"\b(tard|ta7wil|shi7na|chi7na)\b")),
    Cue("impersonation", "Claims to be a bank, telecom or official body",
        "Scammers pose as banks, OMT/Whish, touch/alfa, or the government. Contact them on their official number.",
        (r"\b(omt|whish|blom|bank audi|byblos|fransabank|bankmed|touch lebanon|alfa telecom|mtc touch|ogero|libanpost|"
         r"customer (service|support)|security (team|department)|whatsapp support)\b",
         r"(البنك|مصرف|خدمه العملاء|ادارة الامن|واتساب الرسمي|وزاره)")),
)

_COMPILED = [(c, [re.compile(p, re.IGNORECASE) for p in c.patterns]) for c in CUES]


def text_cue_signals(text: str) -> list[Signal]:
    if not text.strip():
        return []
    norm = normalize_arabic(text)
    hits: list[tuple[Cue, str]] = []
    for cue, patterns in _COMPILED:
        for p in patterns:
            m = p.search(norm)
            if m:
                hits.append((cue, m.group(0).strip()))
                break
    if not hits:
        return []
    # One cue is a hint; several together are the usual shape of a scam script.
    severity = Severity.medium if len(hits) >= 2 else Severity.low
    return [
        Signal(id=f"cue_{cue.id}", title=cue.title, detail=f"Matched “{phrase}”. {cue.why}",
               severity=severity, label=EvidenceLabel.automated_indicator, source="amaan")
        for cue, phrase in hits
    ]
