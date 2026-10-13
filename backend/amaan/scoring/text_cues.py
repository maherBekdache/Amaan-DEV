"""Scam-script cues for messages (English, Arabic, Arabizi).

A transparent, rule-based placeholder for the future scam-intent model:
every cue says exactly which words matched and why that matters.

How it decides:
1. Normalize the text: Arabic letter variants (أ/إ/آ→ا, ئ/ؤ→ء, ة→ه, ى→ي), and
   for Arabizi a consonant "skeleton" per word (vowels dropped, repeats
   collapsed), so b3atle, ba3atli, ab3atli and eb3atle all read as "b3tl".
2. Find cues (asks for a code, prize, money request, urgency, big amount,
   "click the link", delivery story, impersonation).
3. Add up weights. One weak cue stays a hint; a strong cue or several cues
   together become a "scam script" signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from amaan.schemas import EvidenceLabel, Severity, Signal

_AR_DIACRITICS = re.compile(r"[ً-ٰٟـ]")


def normalize_arabic(text: str) -> str:
    text = _AR_DIACRITICS.sub("", text)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ئ", "ء"), ("ؤ", "ء"), ("ة", "ه"), ("ى", "ي")):
        text = text.replace(a, b)
    return text


# --- Arabizi skeletons ----------------------------------------------------------

_LATIN_WORD = re.compile(r"[a-z0-9']+", re.IGNORECASE)


def skeleton(word: str) -> str:
    """b3atle -> b3tl, ekbos -> kbs, rbe7t -> rb7t, 7awwelli -> 7wl."""
    w = re.sub(r"[aeiouy']", "", word.lower())
    return re.sub(r"(.)\1+", r"\1", w)


def _words(text: str) -> list[tuple[str, str]]:
    return [(w, skeleton(w)) for w in _LATIN_WORD.findall(text)]


def _first(words, test) -> str | None:
    return next((w for w, s in words if test(w.lower(), s)), None)


SEND_SK = ("b3t", "3tn", "wrjn")  # ab3atli / ba3atle (send me), a3tini (give me), warjine (show me)
CODE_WORDS = {"code", "codes", "otp", "pin", "ramz"}
CODE_SK = {"cd", "kd", "rmz"}


def _arabizi_code(words) -> str | None:
    send = _first(words, lambda w, s: s.startswith(SEND_SK))
    code = _first(words, lambda w, s: w in CODE_WORDS or s in CODE_SK)
    return f"{send} … {code}" if send and code else None


ARABIZI: dict[str, Callable[[list[tuple[str, str]]], str | None]] = {
    "asks_for_code": _arabizi_code,
    "prize": lambda ws: _first(ws, lambda w, s: s in {"rb7t", "rb7ti", "j2z", "jz", "jyz", "fzt"}),
    "money_request": lambda ws: _first(ws, lambda w, s: s.startswith(("7wl", "sh7n", "ch7n", "df3")) or s == "msr"),
    "urgency_threat": lambda ws: _first(ws, lambda w, s: re.match(r"^[yt]?skr", s) is not None or "st3jl" in s),
    "click_link": lambda ws: _first(ws, lambda w, s: s.startswith(("kbs", "dght", "2bs"))),
}


# --- cues -----------------------------------------------------------------------


@dataclass(frozen=True)
class Cue:
    id: str
    title: str
    why: str
    weight: int
    patterns: tuple[str, ...]


CUES: tuple[Cue, ...] = (
    Cue("asks_for_code", "Asks you to share a code",
        "Banks, OMT, Whish and WhatsApp never ask you to send a verification code. Sharing it gives away your account.",
        3,
        (r"\b(otp|verification code|security code|pin code|6[- ]?digit code|whatsapp code)\b",
         r"\b(send|forward|give|share|tell)( me)? (the |your |that |this )?(code|otp|pin)\b",
         r"(رمز|كود) (التحقق|التاكيد|الامان|التفعيل)",
         r"(ابعت|ابعتلي|بعتلي|ارسل|ارسلي|ابعث|اعطيني|عطيني)\s*(لي\s*)?(ال)?(كود|رمز|الرمز)")),
    Cue("prize", "Prize, gift or lottery",
        "Unexpected prizes that need a fee, a code or your details are a classic scam.",
        2,
        (r"\b(you('ve| have)? won|winner|claim your (prize|reward|gift)|free (gift|iphone)|lottery|prize)\b",
         r"(ربحت|ربحتي|فزت|جايزه|جاءزه|هديه مجانيه|سحب على)")),
    Cue("money_request", "Asks for money or a transfer",
        "Requests to transfer money, pay a 'fee' or top up a number are the end goal of most scams.",
        2,
        (r"\b(transfer|send money|wire|top[- ]?up|recharge|usdt|bitcoin|crypto)\b",
         r"\bpay\b[^.!?\n]{0,30}\b(fee|fees|charge|amount)\b",
         r"(حول|حولي|حوللي|تحويل|ابعتلي مصاري|رسوم|اشحن|تشريج|ادفع)")),
    Cue("urgency_threat", "Pressure or threat",
        "Scams create urgency (account blocked, last chance) so you act before thinking.",
        2,
        (r"\b(urgent|immediately|within 24 hours|account (will be )?(suspended|blocked|closed|locked)|last (chance|warning))\b",
         r"(عاجل|فورا|خلال 24 ساعه|سيتم (ايقاف|اغلاق|حظر|تعليق)|حسابك (موقوف|مقفل|محظور))")),
    Cue("big_amount", "Promises or mentions a large amount of money",
        "Big sums of money out of nowhere are bait.",
        1,
        (r"(\$\s?\d[\d,.]*|\d[\d,.]*\s?(\$|usd|dollars?|euros?|€))",
         r"\b(million|millions|1m)\b",
         r"(مليون|الف دولار|\d+\s*دولار)")),
    Cue("click_link", "Pushes you to click a link",
        "Messages that rush you to a link usually lead to a fake login or payment page.",
        1,
        (r"\b(click|tap|press|open)( on)? (here|the link|this link|below|now)\b",
         r"(اضغط|انقر|اكبس|كبوس|ادخل)\s*(على|ع)?\s*(ال)?(رابط|لينك|ينك)",
         r"(اضغط|انقر|اكبس) (هنا|هون)")),
    Cue("delivery_lure", "Parcel or delivery pretext",
        "Fake 'your parcel is waiting' messages lead to payment or login pages.",
        1,
        (r"\b(parcel|package|shipment|delivery|customs fee|track(ing)? your)\b",
         r"(طرد|شحنه|توصيل|جمرك|رسوم الجمارك)")),
    Cue("impersonation", "Claims to be a bank, telecom or official body",
        "Scammers pose as banks, OMT/Whish, touch/alfa, or the government. Contact them on their official number.",
        1,
        (r"\b(omt|whish|blom|bank audi|byblos|fransabank|bankmed|touch lebanon|alfa telecom|mtc touch|ogero|libanpost|"
         r"customer (service|support)|security (team|department)|whatsapp support)\b",
         r"(البنك|مصرف|خدمه العملاء|اداره الامن|واتساب الرسمي|وزاره)")),
)

# Patterns go through the same Arabic normalization as the messages (على -> علي, ...).
_COMPILED = [(c, [re.compile(normalize_arabic(p), re.IGNORECASE) for p in c.patterns]) for c in CUES]
COMBO_THRESHOLD = 4  # e.g. code request + a link, or prize + big amount + "click"


def _signal(id_: str, title: str, detail: str, severity: Severity) -> Signal:
    return Signal(id=id_, title=title, detail=detail, severity=severity,
                  label=EvidenceLabel.automated_indicator, source="amaan")


def text_cue_signals(text: str, has_link: bool | None = None) -> list[Signal]:
    if not text.strip():
        return []
    norm = normalize_arabic(text)
    words = _words(norm)
    hits: list[tuple[Cue, str]] = []
    for cue, patterns in _COMPILED:
        phrase = next((m.group(0).strip() for p in patterns if (m := p.search(norm))), None)
        if phrase is None and cue.id in ARABIZI:
            phrase = ARABIZI[cue.id](words)
        if phrase:
            hits.append((cue, phrase))
    if not hits:
        return []

    if has_link is None:
        from amaan.extract.urls import extract_urls

        has_link = bool(extract_urls(text, limit=1).urls)
    score = sum(c.weight for c, _ in hits) + (1 if has_link else 0)

    # A single weak cue is only a hint; a strong cue (a code request) or
    # several cues together carry real weight.
    severity = Severity.medium if score >= 3 else Severity.low
    signals = [_signal(f"cue_{c.id}", c.title, f"Matched “{phrase}”. {c.why}", severity) for c, phrase in hits]
    if score >= COMBO_THRESHOLD and len(hits) + int(has_link) >= 2:
        parts = [c.title.lower() for c, _ in hits] + (["contains a link"] if has_link else [])
        signals.insert(0, _signal(
            "cue_scam_script", "Matches a common scam script",
            "Together these are the typical shape of a scam message: " + "; ".join(parts) + ".",
            Severity.high,
        ))
    return signals
