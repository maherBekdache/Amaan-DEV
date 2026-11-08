"""Amaan's own, fully local checks. Every result is a labelled Signal.

These run even when URL.vet is down, and add checks URL.vet does not know
about (Lebanese brands, QR payload risks, hidden characters in messages).
"""

from __future__ import annotations

import re
import unicodedata

from amaan.data import load
from amaan.extract.payloads import CRYPTO_SCHEMES, Payload
from amaan.extract.urls import (
    ExtractedUrl,
    TextFlags,
    defang,
    extract_urls,
    nested_links,
    to_unicode_host,
)
from amaan.schemas import EvidenceLabel, ItemKind, Severity, Signal

# Words scam domains use to look rewarding or official. Matched inside the
# domain name only (not the path), and never on official/known domains.
BAIT_WORDS = ("prize", "winner", "win", "gift", "bonus", "reward", "lottery", "lucky", "claim", "free",
              "verify", "verification", "secure", "login", "signin", "update", "wallet", "airdrop", "promo")

FILE_LIKE_TLDS = {"zip", "mov", "exe", "pdf", "doc", "apk", "scr"}  # those that exist as TLDs: zip, mov

# Characters from other scripts that look like Latin letters, plus common
# digit swaps. Used only to compare a domain's "skeleton" to brand names.
CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ԁ": "d", "һ": "h", "ӏ": "l", "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "ѕ": "s",
    "ԛ": "q", "ԝ": "w", "ɡ": "g", "ο": "o", "α": "a", "ν": "v", "ρ": "p", "τ": "t", "ι": "i",
    "κ": "k", "χ": "x", "ε": "e", "υ": "u", "0": "o", "1": "l", "3": "e", "5": "s", "@": "a",
})


def _sig(id: str, title: str, detail: str, severity: Severity,
         label: EvidenceLabel = EvidenceLabel.automated_indicator) -> Signal:
    return Signal(id=id, title=title, detail=detail, severity=severity, label=label, source="amaan")


def _data() -> dict:
    return load("brands.json")


def official_domains() -> dict[str, str]:
    return {d: b["name"] for b in _data()["brands"] for d in b["domains"]}


def shorteners() -> set[str]:
    return set(_data()["shorteners"])


def skeleton(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(CONFUSABLES)
    return s.replace("rn", "m").replace("vv", "w")


def _scripts(label: str) -> set[str]:
    out = set()
    for ch in label:
        if ch.isascii():
            if ch.isalpha():
                out.add("latin")
            continue
        name = unicodedata.name(ch, "")
        for script in ("LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW", "ARMENIAN"):
            if name.startswith(script):
                out.add(script.lower())
                break
    return out


# Typing errors (typosquatting). Only names of 5+ letters are compared, and only
# with the slips people actually make: a dropped letter (not the first), a doubled
# letter, two letters swapped, or a key next to the right one. Any single edit would
# also flag ordinary words ("finance" against "binance", "cloud" against "icloud").
_KEY_ROWS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")
_KEY_SHIFT = (0.0, 0.5, 0.75, 1.25)  # how far each keyboard row is shifted to the right
_KEY_POS = {c: (r, i + _KEY_SHIFT[r]) for r, row in enumerate(_KEY_ROWS) for i, c in enumerate(row)}


def _near_keys(a: str, b: str) -> bool:
    """True when two keys touch on a QWERTY keyboard."""
    pa, pb = _KEY_POS.get(a), _KEY_POS.get(b)
    if not pa or not pb or a == b:
        return False
    rows, dx = abs(pa[0] - pb[0]), abs(pa[1] - pb[1])
    return (rows == 0 and dx == 1) or (rows == 1 and dx <= 0.75)


def typo_kind(candidate: str, official: str) -> str | None:
    """How `candidate` is a one-slip typing error of `official`, or None."""
    c, o = candidate.lower(), official.lower()
    if c == o or len(o) < 5 or abs(len(c) - len(o)) > 1:
        return None
    if len(c) == len(o):
        diff = [i for i in range(len(o)) if c[i] != o[i]]
        if len(diff) == 1 and _near_keys(c[diff[0]], o[diff[0]]):
            return "a key next to the right one"
        if len(diff) == 2 and diff[1] == diff[0] + 1 and c[diff[0]] == o[diff[1]] and c[diff[1]] == o[diff[0]]:
            return "two letters swapped"
        return None
    if len(c) == len(o) - 1:  # a letter dropped
        i = next((k for k in range(len(c)) if c[k] != o[k]), len(c))
        return "a letter left out" if i > 0 and c == o[:i] + o[i + 1:] else None
    i = next((k for k in range(len(o)) if c[k] != o[k]), len(o))  # a letter added
    if c[:i] + c[i + 1:] != o:
        return None
    extra, near = c[i], [o[k] for k in (i - 1, i) if 0 <= k < len(o)]
    if any(extra == n for n in near):
        return "a letter doubled"
    if any(_near_keys(extra, n) for n in near):
        return "an extra key pressed"
    return None


def url_signals(u: ExtractedUrl) -> list[Signal]:
    sigs: list[Signal] = []
    officials = official_domains()
    reg = u.registrable.lower()
    reg_unicode = to_unicode_host(reg) if reg.startswith("xn--") or ".xn--" in reg else reg
    inner = nested_links(u)

    if inner:
        n = inner[0]
        sigs.append(_sig(
            "hidden_redirect", f"Link forwards to another site ({n.host})",
            f"It starts on {reg} but carries {defang(n.url)} inside it. Trusted sites can be used to pass "
            "you on to a scam page, so Amaan checks the inner link as well.",
            Severity.medium,
        ))

    if reg in officials and not inner:
        sigs.append(_sig(
            "official_domain", f"Official {officials[reg]} domain",
            f"{reg} is on Amaan's curated list of official domains. Still never share codes or passwords over chat.",
            Severity.good, EvidenceLabel.verified,
        ))

    if u.has_userinfo:
        sigs.append(_sig(
            "userinfo_trick", "Link hides its real destination with '@'",
            "Everything before '@' in a link is ignored by the browser, so 'bank.com@evil.site' really opens evil.site.",
            Severity.high,
        ))

    if u.is_ip:
        sigs.append(_sig(
            "ip_host", "Link uses a raw IP address instead of a name",
            f"Legitimate services almost always use a domain name; {u.host} is a bare server address.",
            Severity.medium,
        ))

    if "xn--" in u.host_ascii:
        labels = u.host.split(".")
        mixed = any(len(_scripts(l) - {"arabic"}) > 1 or ("latin" in _scripts(l) and len(_scripts(l)) > 1) for l in labels)
        if mixed:
            sigs.append(_sig(
                "mixed_script", "Domain mixes alphabets (lookalike letters)",
                f"'{u.host}' mixes letters from different alphabets, a classic trick to imitate a real site. "
                f"Its real address is {u.host_ascii}.",
                Severity.high,
            ))
        else:
            sigs.append(_sig(
                "punycode_host", "International (non-Latin) domain",
                f"Shown as '{u.host}', registered as {u.host_ascii}. Check it is the site you expect.",
                Severity.low,
            ))

    # Lookalike / impersonation of a known brand: the strongest finding only.
    if reg not in officials and not u.is_ip:
        sk = skeleton(reg_unicode)
        domain_label = reg_unicode.split(".")[0]
        host_dots = "." + u.host_ascii + "."
        found: Signal | None = None
        for official, brand in officials.items():
            if f".{official}." in host_dots:
                found = _sig(
                    "brand_prefix", f"Starts with {brand}'s address but is another site",
                    f"'{u.host}' begins with {official}, but the site it opens is {reg}.",
                    Severity.high,
                )
                break
        for official, brand in officials.items() if not found else ():
            off_label = official.split(".")[0]
            if sk == skeleton(official) or (skeleton(domain_label) == skeleton(off_label) and domain_label != off_label):
                found = _sig(
                    "lookalike_domain", f"Imitates {brand}'s official domain",
                    f"'{u.host}' looks like {official} but is a different domain.",
                    Severity.high,
                )
                break
        for official, brand in officials.items() if not found else ():
            kind = typo_kind(domain_label, official.split(".")[0])
            if kind:
                found = _sig(
                    "typo_domain", f"Misspells {brand}'s official domain",
                    f"'{u.host}' is {official} with {kind}, a typing error scammers register on purpose.",
                    Severity.high,
                )
                break
        for official, brand in officials.items() if not found else ():
            if domain_label == official.split(".")[0]:
                found = _sig(
                    "brand_other_ending", f"Same name as {brand}'s site, different ending",
                    f"{brand}'s official domain is {official}; {reg} is a different site that anyone could register.",
                    Severity.medium,
                )
                break
        if found:
            sigs.append(found)
        else:
            tokens = set(re.split(r"[.\-_0-9]+", skeleton(u.host)))
            for b in _data()["brands"]:
                hit = next((k for k in b["keywords"] if k in tokens or (len(k) >= 5 and any(k in t for t in tokens))), None)
                if hit:
                    sigs.append(_sig(
                        "brand_in_domain", f"Uses the name '{b['name']}' but is not a known official domain",
                        f"{u.host} contains '{hit}', but {b['name']}'s official domain is {', '.join(b['domains'])}.",
                        Severity.medium,
                    ))
                    break

    if reg not in officials and not u.is_ip and reg not in shorteners():
        name = u.host_ascii.removesuffix("." + u.suffix) if u.suffix else u.host_ascii
        found = [w for w in BAIT_WORDS if w in name.lower()]
        found = [w for w in found if not any(w != o and w in o for o in found)]  # "win" inside "winner"
        if found:
            sigs.append(_sig(
                "bait_domain", "Domain name uses bait words",
                f"'{u.host}' contains {', '.join(repr(w) for w in found)}. Scam sites use names like this "
                "to look rewarding or official.",
                Severity.medium,
            ))

    if reg in shorteners() or u.host_ascii in shorteners():
        sigs.append(_sig(
            "shortener", "Shortened link hides the real destination",
            "Amaan never opens it. URL.vet follows it inside its isolated container to find where it leads.",
            Severity.low,
        ))

    tld = u.suffix.rsplit(".", 1)[-1] if u.suffix else ""
    if tld in FILE_LIKE_TLDS:
        sigs.append(_sig(
            "file_like_tld", f"Domain ending '.{tld}' looks like a file name",
            f"'{u.host}' is a website, not a .{tld} file, a trick used to make links look like attachments.",
            Severity.medium,
        ))

    if u.scheme == "http":
        sigs.append(_sig("no_https", "Not encrypted (http://)",
                         "Anything typed on this page can be read by others on the network.", Severity.low))

    if u.port and u.port not in (80, 443):
        sigs.append(_sig("unusual_port", f"Unusual port :{u.port}",
                         "Normal websites do not need a port number in the link.", Severity.low))

    if reg in ("wa.me", "whatsapp.com") and "/" in u.url.split(u.host_ascii, 1)[-1]:
        sigs.append(_sig("whatsapp_chat_link", "Opens a WhatsApp chat",
                         "This link starts a WhatsApp chat with a number. Check who it is before writing.",
                         Severity.info))
    return sigs


def payload_signals(p: Payload) -> list[Signal]:
    sigs: list[Signal] = []
    if p.kind is ItemKind.wifi:
        sec = p.details.get("security", "")
        if sec.startswith("open"):
            sigs.append(_sig("open_wifi", "Joins an open Wi-Fi network",
                             f"Network '{p.details.get('ssid')}' has no password. Others on it may see your traffic; "
                             "fake hotspots use this to steal logins.", Severity.medium))
        elif sec == "WEP":
            sigs.append(_sig("weak_wifi", "Joins a Wi-Fi network with broken (WEP) security", "", Severity.medium))
        else:
            sigs.append(_sig("wifi", "Joins a Wi-Fi network",
                             f"Scanning connects your phone to '{p.details.get('ssid')}'. Only join networks you trust.",
                             Severity.info))
    elif p.kind is ItemKind.tel:
        num = p.details.get("number", "")
        intl = num.startswith(("+", "00")) and not num.lstrip("+").startswith(("961", "00961"))
        sigs.append(_sig("tel", f"Calls {num}",
                         "Scanning starts a phone call. " + ("This is an international number; calls may be expensive."
                                                             if intl else "Check you know who this number belongs to."),
                         Severity.low if intl else Severity.info))
    elif p.kind is ItemKind.sms:
        has_body = bool(p.details.get("message"))
        sigs.append(_sig("sms", f"Prepares an SMS to {p.details.get('number', '')}",
                         "A ready-made text message can sign you up for paid services or confirm a scam. "
                         "Check the number and message before sending." if has_body else
                         "Scanning opens a new SMS to this number.",
                         Severity.medium if has_body else Severity.low))
    elif p.kind is ItemKind.mailto:
        sigs.append(_sig("mailto", f"Writes an e-mail to {p.details.get('address', '')}", "", Severity.info))
    elif p.kind is ItemKind.geo:
        sigs.append(_sig("geo", "Opens a map location", p.details.get("location", ""), Severity.info))
    elif p.scheme in CRYPTO_SCHEMES:
        sigs.append(_sig("crypto_payment", f"Crypto payment request ({p.scheme})",
                         "Crypto payments cannot be reversed. Scammers often use QR codes to collect them.",
                         Severity.high))
    return sigs


def text_flag_signals(flags: TextFlags) -> list[Signal]:
    sigs: list[Signal] = []
    if flags.bidi_override:
        sigs.append(_sig("bidi_override", "Hidden text-direction characters",
                         "The text contains invisible characters that reverse how letters are displayed, "
                         "used to disguise links and file names.", Severity.high))
    if flags.zero_width_in_link:
        sigs.append(_sig("zero_width", "Invisible characters inside a link",
                         "Zero-width characters were hidden inside a link, often to slip past filters.",
                         Severity.medium))
    if flags.fullwidth:
        sigs.append(_sig("fullwidth", "Unusual wide characters",
                         "The text uses full-width letters or dots, sometimes used to disguise links.",
                         Severity.low))
    if flags.defanged:
        sigs.append(_sig("defanged", "Contains defanged links (e.g. hxxp, [.])",
                         "Security teams write links this way to make them unclickable. We restored them for analysis.",
                         Severity.info))
    return sigs


def link_text_mismatch(href_host: str, anchor_text: str) -> Signal | None:
    """An <a> whose visible text is a different domain than where it goes."""
    shown = extract_urls(anchor_text, limit=1).urls
    if not shown:
        return None
    if shown[0].registrable.lower() == href_host.lower():
        return None
    return _sig("link_text_mismatch", "Link text shows a different site than where it goes",
                f"It displays '{shown[0].host}' but actually opens {href_host}.", Severity.high)
