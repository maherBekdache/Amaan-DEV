"""Classify what a QR code contains: URL, Wi-Fi, phone, SMS, e-mail, geo, text.

Only URL payloads are sent to URL.vet. Everything else is described to the
user so they know what scanning the code on a phone would do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlsplit

from amaan.schemas import ItemKind

CRYPTO_SCHEMES = {"bitcoin", "ethereum", "litecoin", "tron", "usdt", "bnb", "solana", "dogecoin", "monero"}


@dataclass
class Payload:
    kind: ItemKind
    raw: str
    details: dict[str, str] = field(default_factory=dict)
    scheme: str | None = None


def _split_mecard(body: str) -> dict[str, str]:
    """Parse 'K:v;K2:v2;;' with backslash escapes (Wi-Fi and MECARD format)."""
    fields: dict[str, str] = {}
    key, buf, i = None, [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            buf.append(body[i + 1])
            i += 2
            continue
        if ch == ":" and key is None:
            key, buf = "".join(buf).upper(), []
        elif ch == ";":
            if key is not None:
                fields.setdefault(key, "".join(buf))
            key, buf = None, []
        else:
            buf.append(ch)
        i += 1
    if key is not None:
        fields.setdefault(key, "".join(buf))
    return fields


def classify_payload(text: str) -> Payload:
    raw = text.strip()
    lower = raw.lower()

    if lower.startswith("wifi:"):
        f = _split_mecard(raw[5:])
        security = (f.get("T") or "nopass").upper()
        details = {
            "ssid": f.get("S", ""),
            "security": "open (no password)" if security in ("NOPASS", "") else security,
            "hidden": "yes" if f.get("H", "").lower() == "true" else "no",
            # Never echo the password back; just say whether there is one.
            "password": "included (hidden)" if f.get("P") else "none",
        }
        return Payload(ItemKind.wifi, raw, details, "wifi")

    if lower.startswith("tel:"):
        return Payload(ItemKind.tel, raw, {"number": unquote(raw[4:]).strip()}, "tel")

    if lower.startswith(("sms:", "smsto:", "mms:", "mmsto:")):
        scheme, _, rest = raw.partition(":")
        number, body = rest, ""
        if "?" in rest:  # sms:+961...?body=...
            number, _, q = rest.partition("?")
            body = parse_qs(q).get("body", [""])[0]
        elif ":" in rest:  # SMSTO:number:body
            number, _, body = rest.partition(":")
        details = {"number": unquote(number).strip()}
        if body:
            details["message"] = unquote(body)[:300]
        return Payload(ItemKind.sms, raw, details, scheme.lower())

    if lower.startswith("mailto:"):
        parts = urlsplit(raw)
        q = parse_qs(parts.query)
        details = {"address": unquote(parts.path)}
        if q.get("subject"):
            details["subject"] = q["subject"][0][:200]
        return Payload(ItemKind.mailto, raw, details, "mailto")

    if lower.startswith("matmsg:"):
        f = _split_mecard(raw[7:])
        return Payload(ItemKind.mailto, raw, {"address": f.get("TO", ""), "subject": f.get("SUB", "")[:200]}, "matmsg")

    if lower.startswith("geo:"):
        return Payload(ItemKind.geo, raw, {"location": raw[4:].split("?")[0]}, "geo")

    if re.match(r"^(https?|ftp)://", lower) or re.match(r"^www\.", lower):
        return Payload(ItemKind.url, raw, {}, lower.split(":", 1)[0] if "://" in lower else None)

    scheme_m = re.match(r"^([a-z][a-z0-9+.\-]{1,20}):", lower)
    if scheme_m and scheme_m.group(1) in CRYPTO_SCHEMES:
        scheme = scheme_m.group(1)
        address = raw.split(":", 1)[1].split("?")[0]
        q = parse_qs(raw.split("?", 1)[1]) if "?" in raw else {}
        details = {"currency": scheme, "address": address}
        if q.get("amount"):
            details["amount"] = q["amount"][0]
        return Payload(ItemKind.text, raw, details, scheme)

    if lower.startswith(("mecard:", "begin:vcard")):
        return Payload(ItemKind.text, raw, {"format": "contact card"}, lower.split(":", 1)[0])

    # Anything else is plain text (it may still contain bare-domain links,
    # which the caller extracts with the normal URL extractor).
    other_scheme = scheme_m.group(1) if scheme_m and "://" in lower else None
    return Payload(ItemKind.text, raw, {"scheme": other_scheme} if other_scheme else {}, other_scheme)
