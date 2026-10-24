import base64

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from amaan.config import get_settings
from amaan.reputation import safebrowsing, urlscan, virustotal
from amaan.reputation.base import SourceResult, SourceStatus, SourceVerdict
from amaan.reputation.feeds import Feed, FeedStore
from amaan.scoring import aggregate
from amaan.schemas import EvidenceLabel, Severity

S = get_settings()


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


# --- downloaded lists -----------------------------------------------------------------


def test_feed_exact_and_host_match():
    f = Feed("OpenPhish", "x")
    f.load_text("https://omt-gift.example.com/claim\nhttps://sites.google.com/view/fake-bank\n# comment\n")
    assert f.check("http://www.omt-gift.example.com/claim").verdict is SourceVerdict.malicious
    assert "Other pages" in f.check("https://omt-gift.example.com/other").detail
    # shared hosting: one bad page must not flag every Google Sites page
    assert f.check("https://sites.google.com/view/my-school").verdict is SourceVerdict.clean
    assert f.check("https://www.aub.edu.lb").verdict is SourceVerdict.clean


def test_feeds_off_and_urlhaus_needs_key():
    assert FeedStore(None, enabled=False).check("x.com")[0].status is SourceStatus.not_configured
    names = [r.source for r in FeedStore(None, enabled=True).check("x.com")]
    assert names == ["OpenPhish", "URLhaus"]
    assert FeedStore(None, enabled=True).check("x.com")[1].status is SourceStatus.not_configured


# --- Google Safe Browsing (hash prefixes only) ------------------------------------------


def test_safebrowsing_expressions_follow_spec():
    ex = safebrowsing.expressions("https://a.b.c.d.e.f.example.com/1/2.html?x=1")
    assert "a.b.c.d.e.f.example.com/1/2.html?x=1" in ex and "example.com/" in ex
    assert len(ex) <= 30
    assert safebrowsing.expressions("http://1.2.3.4/a") == ["1.2.3.4/a", "1.2.3.4/"]


@respx.mock
async def test_safebrowsing_sends_only_prefixes_and_matches_locally(client):
    url = "https://phish.example.com/login"
    target = safebrowsing.full_hash("phish.example.com/login")

    def answer(request: httpx.Request):
        assert "phish" not in str(request.url)  # the link itself never leaves
        assert all(len(base64.b64decode(p)) == 4 for p in request.url.params.get_list("hashPrefixes"))
        return httpx.Response(200, json={"fullHashes": [{
            "fullHash": base64.b64encode(target).decode(),
            "fullHashDetails": [{"threatType": "SOCIAL_ENGINEERING"}]}]})

    respx.get(safebrowsing.API).mock(side_effect=answer)
    r = await safebrowsing.check(url, "KEY", client)
    assert r.verdict is SourceVerdict.malicious and "phishing" in r.detail


@respx.mock
async def test_safebrowsing_prefix_collision_is_not_a_hit(client):
    other = b"\x00" * 32
    respx.get(safebrowsing.API).mock(return_value=httpx.Response(200, json={"fullHashes": [
        {"fullHash": base64.b64encode(other).decode(), "fullHashDetails": [{"threatType": "MALWARE"}]}]}))
    assert (await safebrowsing.check("https://ok.example.com", "KEY", client)).verdict is SourceVerdict.clean


async def test_safebrowsing_without_key(client):
    assert (await safebrowsing.check("x.com", None, client)).status is SourceStatus.not_configured


# --- VirusTotal (lookup only) -------------------------------------------------------------


@respx.mock
async def test_virustotal_verdicts(client):
    virustotal.limiter.calls.clear()
    route = respx.get(url__startswith=virustotal.API)
    route.mock(return_value=httpx.Response(200, json={"data": {"attributes": {"last_analysis_stats": {
        "malicious": 5, "suspicious": 1, "harmless": 60, "undetected": 20}}}}))
    r = await virustotal.check("http://bad.example.com/x", "KEY", client)
    assert r.verdict is SourceVerdict.malicious and "5 of 86" in r.detail
    assert route.calls.last.request.headers["x-apikey"] == "KEY"
    assert route.calls.last.request.method == "GET"  # never submits new links
    route.mock(return_value=httpx.Response(404))
    assert (await virustotal.check("http://new.example.com", "KEY", client)).verdict is SourceVerdict.unknown


def test_virustotal_url_id():
    assert virustotal.url_id("http://example.com/") == "aHR0cDovL2V4YW1wbGUuY29tLw"


# --- urlscan.io (private scan) -------------------------------------------------------------


@respx.mock
async def test_urlscan_private_scan(client):
    sub = respx.post(f"{urlscan.API}/scan/").mock(return_value=httpx.Response(200, json={"uuid": "u1"}))
    respx.get(f"{urlscan.API}/result/u1/").mock(side_effect=[
        httpx.Response(404),
        httpx.Response(200, json={"verdicts": {"overall": {"malicious": True, "score": 100, "brands": ["PayPal"]}}}),
    ])
    r = await urlscan.check("paypal-login.example.com", "KEY", client, first_wait=0, poll_every=0)
    assert r.verdict is SourceVerdict.malicious and "PayPal" in r.detail
    import json
    assert json.loads(sub.calls.last.request.content)["visibility"] == "private"


# --- combining ------------------------------------------------------------------------------


def test_source_signals():
    def ok(name, v, community=False):
        return SourceResult(source=name, kind="x", status=SourceStatus.ok, verdict=v, community=community, detail="d")

    sig = aggregate.source_signals([ok("OpenPhish", SourceVerdict.malicious, True), ok("VirusTotal", SourceVerdict.clean)])
    assert sig[0].severity is Severity.high and sig[0].label is EvidenceLabel.community_report
    sig = aggregate.source_signals([ok("VirusTotal", SourceVerdict.clean), ok("OpenPhish", SourceVerdict.clean, True),
                                    SourceResult(source="urlscan.io", kind="x", status=SourceStatus.not_configured)])
    assert sig[0].id == "sources_clean" and "2 security sources" in sig[0].title


@respx.mock
def test_analyze_link_endpoint_runs_all_sources(monkeypatch):
    from amaan.main import app

    monkeypatch.setattr(S, "virustotal_key", "KEY")
    virustotal.limiter.calls.clear()
    respx.route(host="testserver").pass_through()
    respx.get(f"{S.urlvet_base_url}/api/v1/analyze").mock(
        return_value=httpx.Response(200, json={"result": {"verdict": "Safe", "final_score": 80, "reasons": {}}}))
    respx.get(url__startswith=virustotal.API).mock(return_value=httpx.Response(200, json={"data": {"attributes": {
        "last_analysis_stats": {"malicious": 7, "suspicious": 0, "harmless": 50, "undetected": 30}}}}))
    with TestClient(app) as c:
        ev = c.post("/analyze/link", json={"urls": ["https://fresh-scam.example.com/win"]}).json()
        assert ev["risk_level"] == "High"
        item = ev["items"][0]
        assert {s["source"] for s in item["sources"]} >= {"VirusTotal", "Google Safe Browsing", "urlscan.io"}
        assert any(s["title"] == "VirusTotal flags it as dangerous" for s in item["signals"])
        assert c.post("/analyze/link", json={"urls": [" "]}).status_code == 400
