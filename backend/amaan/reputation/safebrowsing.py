"""Google Safe Browsing v5 (hashes:search): only 4-byte hash prefixes leave the machine.

The link is turned into the host/path "expressions" defined by Safe Browsing,
each is SHA-256 hashed, and only the first 4 bytes of each hash are sent.
Google answers with full hashes that start with those prefixes; we compare
them locally. Google never learns the link itself.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import posixpath
from functools import partial
from urllib.parse import unquote, urlsplit

import httpx

from amaan.reputation.base import SourceResult, SourceStatus, SourceVerdict

API = "https://safebrowsing.googleapis.com/v5/hashes:search"
NAME = "Google Safe Browsing"
_result = partial(SourceResult, source=NAME, kind="blocklist")
NAMES = {"MALWARE": "malware", "SOCIAL_ENGINEERING": "phishing / deceptive site",
         "UNWANTED_SOFTWARE": "unwanted software", "POTENTIALLY_HARMFUL_APPLICATION": "harmful app"}


def _canonical(url: str) -> tuple[str, str, str]:
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    p = urlsplit(u)
    host = (p.hostname or "").strip(".").lower()
    while ".." in host:
        host = host.replace("..", ".")
    path = posixpath.normpath(unquote(p.path or "/")) if p.path not in ("", "/") else "/"
    if (p.path or "/").endswith("/") and not path.endswith("/"):
        path += "/"
    path = path.replace("//", "/")
    return host, path, p.query


def expressions(url: str) -> list[str]:
    """Host-suffix x path-prefix combinations (at most 5 x 6 = 30)."""
    host, path, query = _canonical(url)
    try:
        ipaddress.ip_address(host)
        hosts = [host]
    except ValueError:
        parts = host.split(".")
        hosts = [host] + [".".join(parts[i:]) for i in range(max(1, len(parts) - 5), len(parts) - 1)]
        hosts = list(dict.fromkeys(hosts))[:5]
    paths = []
    if query:
        paths.append(f"{path}?{query}")
    paths.append(path)
    segs = [s for s in path.split("/") if s]
    if not path.endswith("/"):
        segs = segs[:-1]  # the last part is a file, not a folder
    acc = "/"
    paths.append(acc)
    for s in segs[:3]:
        acc += s + "/"
        paths.append(acc)
    paths = list(dict.fromkeys(paths))[:6]
    return [h + p for h in hosts for p in paths]


def full_hash(expr: str) -> bytes:
    return hashlib.sha256(expr.encode()).digest()


async def check(url: str, api_key: str | None, client: httpx.AsyncClient) -> SourceResult:
    if not api_key:
        return _result(status=SourceStatus.not_configured,
                       detail="Needs a free Google API key (AMAAN_SAFE_BROWSING_KEY).")
    hashes = {full_hash(e) for e in expressions(url)}
    prefixes = sorted({base64.b64encode(h[:4]).decode() for h in hashes})
    try:
        r = await client.get(API, params=[("key", api_key), *[("hashPrefixes", p) for p in prefixes]], timeout=10)
    except httpx.TimeoutException:
        return _result(status=SourceStatus.timeout, detail="No answer in time.")
    except httpx.HTTPError:
        return _result(status=SourceStatus.error, detail="Not reachable.")
    if r.status_code == 429:
        return _result(status=SourceStatus.rate_limited, detail="Quota reached.")
    if r.status_code != 200:
        return _result(status=SourceStatus.error, detail=f"HTTP {r.status_code}.")
    try:
        found = r.json().get("fullHashes") or []
    except ValueError:
        return _result(status=SourceStatus.error, detail="Unreadable answer.")
    threats: set[str] = set()
    for fh in found:
        try:
            if base64.b64decode(fh.get("fullHash", "")) in hashes:
                threats |= {d.get("threatType", "") for d in fh.get("fullHashDetails") or [] if d.get("threatType")}
        except (ValueError, TypeError):
            continue
    if threats:
        kinds = ", ".join(sorted(NAMES.get(t, t.lower()) for t in threats))
        return _result(status=SourceStatus.ok, verdict=SourceVerdict.malicious,
                       detail=f"Listed by Google as {kinds}. Advisory provided by Google.")
    return _result(status=SourceStatus.ok, verdict=SourceVerdict.clean,
                   detail="Not on Google's lists.")
