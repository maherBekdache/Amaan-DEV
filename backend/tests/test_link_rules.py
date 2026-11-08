"""Typing errors, brand prefixes, other endings and links hidden inside links
(open redirects). The same cases run on the phone (packages/core parity test)."""

import json
from pathlib import Path

import pytest

from amaan.extract.urls import nested_links, parse_candidate
from amaan.scoring.local_rules import typo_kind, url_signals

CASES = json.loads((Path(__file__).parent / "data" / "link_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["link"][:60])
def test_link_case(case):
    u = parse_candidate(case["link"])
    assert u is not None
    ids = {s.id for s in url_signals(u)}
    assert set(case.get("expect", [])) <= ids
    assert not set(case.get("absent", [])) & ids
    if "inner" in case:
        assert [n.url for n in nested_links(u)] == case["inner"]


def test_typo_kinds():
    assert typo_kind("whsh", "whish") == "a letter left out"
    assert typo_kind("hish", "whish") is None  # first letter dropped: too many real words
    assert typo_kind("whiish", "whish") == "a letter doubled"
    assert typo_kind("whihs", "whish") == "two letters swapped"
    assert typo_kind("wjish", "whish") == "a key next to the right one"
    assert typo_kind("whissh", "whish") == "a letter doubled"
    assert typo_kind("whisgh", "whish") == "an extra key pressed"
    assert typo_kind("omtt", "omt") is None  # names under 5 letters are not compared


def test_inner_link_is_checked_as_its_own_item(client_off):
    ev = client_off.post("/analyze/text", json={
        "text": "Unlock your account: https://www.google.com/url?q=https://whish-unlock.example.com/login"}).json()
    hosts = [i["host_ascii"] for i in ev["items"]]
    assert hosts == ["www.google.com", "whish-unlock.example.com"]
    inner = ev["items"][1]
    assert "brand_in_domain" in {s["id"] for s in inner["signals"]}


def test_official_domain_that_forwards_is_not_verified(client_off):
    ev = client_off.post("/analyze/text", json={
        "text": "https://l.facebook.com/l.php?u=https%3A%2F%2Fwhish-pay.xyz%2Fx"}).json()
    outer = ev["items"][0]
    assert "official_domain" not in {s["id"] for s in outer["signals"]}
    assert outer["risk_level"] != "Low"


def test_link_without_scheme_keeps_its_inner_link_separate(client_off):
    # The phone sends links one per line (uri_list); a scheme-less outer link once shared
    # its key with the link inside it and the two were merged into one item.
    ev = client_off.post("/analyze/text", json={"uri_list": "google.com/url?q=https://evil-site.com/a"}).json()
    assert [i["host_ascii"] for i in ev["items"]] == ["google.com", "evil-site.com"]
