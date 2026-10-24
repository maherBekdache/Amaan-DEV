"""Find URLs in free text (English, Arabic, Arabizi, mixed).

Nothing in this module touches the network: no DNS, no HTTP, no shortener
expansion. The public-suffix list is the snapshot bundled with tldextract.

What it handles:
- links with a scheme (http, https, ftp), www.-prefixed links, bare domains
  (omt-lb.xyz, bit.ly/abc), raw IPs with a port or path
- Arabic punctuation and Arabic letters glued to a link ("زوروا example.com،")
- defanged links (hxxp, example[.]com), full-width dots and letters
- invisible characters: zero-width and bidi control characters are removed
  and reported, because scammers use them to hide or disguise links
- punycode in both directions (xn--... <-> Unicode)
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

import idna
import tldextract

# Offline public-suffix list: suffix_list_urls=() means "never download".
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

ZERO_WIDTH = "​‌‍⁠﻿­᠎"
BIDI_CONTROLS = "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"
BIDI_OVERRIDES = "‭‮"  # LRO / RLO: reverse how text is displayed
DOT_VARIANTS = {"。": ".", "．": ".", "｡": ".", "․": ".", "﹒": "."}

# Characters that end a sentence rather than a URL (Latin and Arabic).
TRAILING_PUNCT = ".,;:!?'\"»«”“’‘…>]}،؛؟۔*_~"

# Letters allowed in a bare (scheme-less) domain: ASCII, Latin-extended,
# Greek and Cyrillic. Greek/Cyrillic are included on purpose so homograph
# domains like "аpple.com" (Cyrillic а) are caught. Arabic letters are left
# out so Arabic words glued to a link do not become part of it; Arabic
# domains are still found when written with a scheme or www.
_L = r"0-9a-zÀ-ɏͰ-ϿЀ-ӿ"
_LABEL = rf"[{_L}](?:[{_L}\-]{{0,61}}[{_L}])?"
_PATH = r"(?:[/?#][^\s<>\"'`]*)?"

SCHEME_RE = re.compile(r"(?<![a-z])(?:https?|ftp)://[^\s<>\"'`]+", re.IGNORECASE)
WWW_RE = re.compile(rf"(?<![{_L}@.\-/])www\d{{0,3}}\.[^\s<>\"'`]+", re.IGNORECASE)
BARE_RE = re.compile(
    rf"(?<![{_L}@.\-/:])(?:{_LABEL}\.)+{_LABEL}(?::\d{{1,5}})?{_PATH}",
    re.IGNORECASE,
)
IP_RE = re.compile(
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5}(?:[/?#][^\s<>\"'`]*)?|[/?#][^\s<>\"'`]*)"
)
DEFANG_RE = [
    (re.compile(r"\bhxxp(s?)\b", re.IGNORECASE), r"http\1"),
    (re.compile(r"\[\s*(?:\.|dot)\s*\]|\(\s*(?:\.|dot)\s*\)|\{\s*(?:\.|dot)\s*\}", re.IGNORECASE), "."),
    (re.compile(r"\[\s*:\s*\]"), ":"),
    (re.compile(r"\[\s*/\s*\]"), "/"),
]
_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


@dataclass
class TextFlags:
    """Things noticed while cleaning the text, reported as signals later."""

    zero_width_in_link: bool = False
    bidi_override: bool = False
    defanged: bool = False
    fullwidth: bool = False


@dataclass
class ExtractedUrl:
    original: str  # as found in the (cleaned) text
    url: str  # what we send to URL.vet: host in punycode form
    host: str  # Unicode, lower-case
    host_ascii: str  # punycode, lower-case
    scheme: str | None
    registrable: str  # e.g. "omt.com.lb"
    suffix: str  # e.g. "com.lb"
    is_ip: bool = False
    has_userinfo: bool = False
    port: int | None = None


@dataclass
class ExtractionResult:
    urls: list[ExtractedUrl]
    flags: TextFlags
    truncated: bool = False  # more URLs than the limit
    cleaned_text: str = ""


def clean_text(text: str) -> tuple[str, TextFlags]:
    """Normalize text before searching it. Returns (clean_text, flags)."""
    flags = TextFlags()
    if any(ch in text for ch in BIDI_OVERRIDES):
        flags.bidi_override = True
    # A zero-width character sitting between link characters is a red flag
    # (it breaks naive filters while the link still looks normal on screen).
    if re.search(rf"[A-Za-z0-9./:][{ZERO_WIDTH}]+[A-Za-z0-9./]", text):
        flags.zero_width_in_link = True
    text = text.translate({ord(c): None for c in ZERO_WIDTH + BIDI_CONTROLS})
    for k, v in DOT_VARIANTS.items():
        text = text.replace(k, v)
    if re.search(r"[！-～]", text):
        flags.fullwidth = True
    text = unicodedata.normalize("NFKC", text)
    for pattern, repl in DEFANG_RE:
        text, n = pattern.subn(repl, text)
        if n:
            flags.defanged = True
    return text, flags


def _trim_trailing(candidate: str) -> str:
    while candidate:
        last = candidate[-1]
        if last == ")" and candidate.count("(") >= candidate.count(")"):
            break  # balanced, e.g. en.wikipedia.org/wiki/Foo_(bar)
        if last in TRAILING_PUNCT or last == ")":
            candidate = candidate[:-1]
            continue
        break
    return candidate


def to_ascii_host(host: str) -> str | None:
    host = host.strip(".").lower()
    if not host:
        return None
    try:
        return idna.encode(host, uts46=True, transitional=False).decode("ascii")
    except idna.IDNAError:
        pass
    try:
        return host.encode("idna").decode("ascii")  # IDNA 2003, more lenient
    except UnicodeError:
        return None


def to_unicode_host(host_ascii: str) -> str:
    try:
        return idna.decode(host_ascii)
    except idna.IDNAError:
        try:
            return host_ascii.encode("ascii").decode("idna")
        except UnicodeError:
            return host_ascii


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def parse_candidate(candidate: str, allow_bare_ip: bool = True) -> ExtractedUrl | None:
    """Validate one candidate string and build an ExtractedUrl (or None).

    allow_bare_ip=False rejects a lone IP like "10.0.0.1" (usually a version
    number or a LAN address in a chat, not a link).
    """
    candidate = _trim_trailing(candidate.strip())
    if not candidate:
        return None
    has_scheme = bool(re.match(r"^[a-z][a-z0-9+.\-]*://", candidate, re.IGNORECASE))
    try:
        parts = urlsplit(candidate if has_scheme else "//" + candidate)
    except ValueError:
        return None
    netloc = parts.netloc
    has_userinfo = "@" in netloc
    hostport = netloc.rsplit("@", 1)[-1]
    host = hostport
    port: int | None = None
    if hostport.startswith("["):  # IPv6 literal
        host = hostport.split("]")[0] + "]"
    elif ":" in hostport:
        host, _, port_s = hostport.rpartition(":")
        if port_s.isdigit():
            port = int(port_s)
        else:
            host = hostport
    rest = candidate.split(netloc, 1)[1] if netloc and netloc in candidate else ""

    # An Arabic word glued to the end of the host ("example.comهنا"):
    # cut the host at the first Arabic letter after the last ASCII dot.
    m = _ARABIC.search(host)
    if m and re.search(r"[a-z]", host[: m.start()], re.IGNORECASE) and "." in host[: m.start()]:
        host = host[: m.start()]
        rest = ""
        port = None

    if _is_ip(host):
        if not allow_bare_ip and not has_scheme and port is None and not rest:
            return None
        host_ascii = host.lower()
        return ExtractedUrl(
            original=candidate,
            url=_rebuild(parts.scheme if has_scheme else None, host_ascii, port, rest),
            host=host_ascii,
            host_ascii=host_ascii,
            scheme=parts.scheme.lower() if has_scheme else None,
            registrable=host_ascii,
            suffix="",
            is_ip=True,
            has_userinfo=has_userinfo,
            port=port,
        )

    host_ascii = to_ascii_host(host)
    if not host_ascii or "." not in host_ascii:
        return None
    ext = _tld.extract_str(host_ascii)
    if not ext.suffix or not ext.domain:
        return None
    tld = ext.suffix.rsplit(".", 1)[-1]
    if not (tld.isalpha() or tld.startswith("xn--")):
        return None
    return ExtractedUrl(
        original=candidate,
        url=_rebuild(parts.scheme if has_scheme else None, host_ascii, port, rest),
        host=to_unicode_host(host_ascii),
        host_ascii=host_ascii,
        scheme=parts.scheme.lower() if has_scheme else None,
        registrable=f"{ext.domain}.{ext.suffix}",
        suffix=ext.suffix,
        has_userinfo=has_userinfo,
        port=port,
    )


def _rebuild(scheme: str | None, host_ascii: str, port: int | None, rest: str) -> str:
    out = f"{scheme.lower()}://" if scheme else ""
    out += host_ascii
    if port is not None:
        out += f":{port}"
    return out + rest


def extract_urls(text: str, limit: int = 50) -> ExtractionResult:
    """Find every URL in `text`, in order of appearance, without duplicates."""
    cleaned, flags = clean_text(text)
    found: list[tuple[int, ExtractedUrl]] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < e and s < end for s, e in taken)

    for regex in (SCHEME_RE, WWW_RE, IP_RE, BARE_RE):
        for m in regex.finditer(cleaned):
            start, end = m.span()
            if overlaps(start, end):
                continue
            if regex is BARE_RE and end < len(cleaned) and cleaned[end] == "@":
                continue  # the local part of an email address: name.surname@
            parsed = parse_candidate(m.group(0), allow_bare_ip=regex is not BARE_RE)
            if parsed is None:
                continue
            taken.append((start, start + len(parsed.original)))
            found.append((start, parsed))

    found.sort(key=lambda t: t[0])
    unique: list[ExtractedUrl] = []
    seen: set[str] = set()
    for _, u in found:
        key = u.url.lower().rstrip("/")
        key = re.sub(r"^[a-z]+://", "", key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(u)
    truncated = len(unique) > limit
    return ExtractionResult(urls=unique[:limit], flags=flags, truncated=truncated, cleaned_text=cleaned)


def defang(value: str) -> str:
    """Make a URL safe to display: not clickable, not auto-linked by apps."""
    value = re.sub(r"^http", "hxxp", value, flags=re.IGNORECASE)
    value = re.sub(r"^ftp", "fxp", value, flags=re.IGNORECASE)
    head, sep, tail = value.partition("://")
    target = tail if sep else head
    host_end = re.search(r"[/?#]", target)
    host_part = target[: host_end.start()] if host_end else target
    rest = target[len(host_part):]
    host_part = host_part.replace(".", "[.]")
    return f"{head}{sep}{host_part}{rest}" if sep else f"{host_part}{rest}"
