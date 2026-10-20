"""Links to other sites' own rating of a link (VirusTotal, Safe Browsing, URLVoid, …).

Amaan only builds the addresses; nothing is fetched. The user opens one by clicking,
which shares that link with that site (said next to the list).
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from urllib.parse import quote

from pydantic import BaseModel


class Lookup(BaseModel):
    id: str
    name: str
    about: str
    href: str


@lru_cache(maxsize=1)
def _sites() -> list[dict]:
    return json.loads(resources.files("amaan.data").joinpath("lookups.json").read_text(encoding="utf-8"))["sites"]


def lookup_links(url: str, host_ascii: str) -> list[Lookup]:
    if "://" not in url:
        url = "http://" + url  # "omt-gift.com/claim": the sites expect a full URL
    enc = quote(url, safe="")
    values = {"{url}": enc, "{url2}": quote(enc, safe=""), "{host}": quote(host_ascii, safe=".-")}
    out = []
    for s in _sites():
        href = s["template"]
        for k, v in values.items():
            href = href.replace(k, v)
        out.append(Lookup(id=s["id"], name=s["name"], about=s["about"], href=href))
    return out
