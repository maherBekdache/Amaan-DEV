import httpx
import pytest
import respx

from amaan.clients.urlvet import UrlVetClient, parse_report
from amaan.schemas import UrlVetStatus

BASE = "http://urlvet.test:8080"

RISKY = {
    "url": "https://omt-lb.xyz/claim",
    "domain": "omt-lb.xyz",
    "short_link": {"url": "https://bit.ly/x", "chain": ["https://bit.ly/x", "https://omt-lb.xyz/claim"],
                   "target": "https://omt-lb.xyz/claim", "resolved": True},
    "threat_feeds": {"listed": True, "match": "url", "sources": ["PhishTank"], "checked": ["PhishTank"]},
    "result": {"risk_score": 90, "trust_score": 10, "final_score": 10, "verdict": "Risky",
               "reasons": {"bad_reasons": ["Domain registered 3 days ago.", "Login form on a new domain."],
                           "good_reasons": None, "neutral_reasons": None}},
    "incomplete": False,
}


@pytest.fixture
async def client():
    c = UrlVetClient(BASE, timeout_s=2.0)
    yield c
    await c.aclose()


def test_parse_report_maps_fields():
    r = parse_report(RISKY)
    assert r.status is UrlVetStatus.ok
    assert r.verdict == "Risky" and r.final_score == 10 and r.trust_score == 10 and r.risk_score == 90
    assert r.bad_reasons == ["Domain registered 3 days ago.", "Login form on a new domain."]
    assert r.good_reasons == []
    assert r.threat_listed and r.threat_sources == ["PhishTank"]
    assert r.redirect_chain == ["hxxps://bit[.]ly/x", "hxxps://omt-lb[.]xyz/claim"]
    assert r.final_url == "hxxps://omt-lb[.]xyz/claim"


def test_parse_unresolved_short_link():
    r = parse_report({"short_link": {"resolved": False, "chain": ["https://bit.ly/x"]},
                      "result": {"verdict": "Suspicious", "final_score": 40, "reasons": {}}})
    assert any("could not find" in n for n in r.neutral_reasons)


def test_parse_tolerates_missing_fields():
    r = parse_report({})
    assert r.status is UrlVetStatus.ok and r.verdict is None and r.redirect_chain == []


@respx.mock
async def test_analyze_ok(client):
    route = respx.get(f"{BASE}/api/v1/analyze").mock(return_value=httpx.Response(200, json=RISKY))
    r = await client.analyze("https://bit.ly/x")
    assert r.verdict == "Risky" and r.elapsed_ms is not None
    assert route.calls.last.request.url.params["url"] == "https://bit.ly/x"


@respx.mock
async def test_bare_domain_retry_with_scheme(client):
    route = respx.get(f"{BASE}/api/v1/analyze").mock(
        side_effect=[httpx.Response(400, json={"error": "invalid url"}), httpx.Response(200, json=RISKY)])
    r = await client.analyze("omt-lb.xyz/claim")
    assert r.status is UrlVetStatus.ok
    assert route.calls[1].request.url.params["url"] == "https://omt-lb.xyz/claim"


@respx.mock
async def test_down(client):
    respx.get(f"{BASE}/api/v1/analyze").mock(side_effect=httpx.ConnectError("refused"))
    r = await client.analyze("https://example.com")
    assert r.status is UrlVetStatus.unavailable


@respx.mock
async def test_timeout(client):
    respx.get(f"{BASE}/api/v1/analyze").mock(side_effect=httpx.ReadTimeout("slow"))
    assert (await client.analyze("https://example.com")).status is UrlVetStatus.timeout


@respx.mock
async def test_rate_limited(client):
    respx.get(f"{BASE}/api/v1/analyze").mock(return_value=httpx.Response(429, json={"error": "too many requests"}))
    assert (await client.analyze("https://example.com")).status is UrlVetStatus.rate_limited


@respx.mock
async def test_rejected(client):
    respx.get(f"{BASE}/api/v1/analyze").mock(return_value=httpx.Response(422, json={"error": "could not analyze"}))
    r = await client.analyze("https://example.com")
    assert r.status is UrlVetStatus.rejected and "could not analyze" in r.message


@respx.mock
async def test_garbage_response(client):
    respx.get(f"{BASE}/api/v1/analyze").mock(return_value=httpx.Response(200, text="<html>oops"))
    assert (await client.analyze("https://example.com")).status is UrlVetStatus.error


@respx.mock
async def test_server_error(client):
    respx.get(f"{BASE}/api/v1/analyze").mock(return_value=httpx.Response(502))
    assert (await client.analyze("https://example.com")).status is UrlVetStatus.error


@respx.mock
async def test_health(client):
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    assert (await client.health())["reachable"] is True
    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("x"))
    assert (await client.health())["reachable"] is False


def test_mock_is_labelled():
    r = parse_report({"_mock": True, "result": {"verdict": "Safe", "final_score": 85, "reasons": {}}})
    assert r.mock and r.neutral_reasons[0].startswith("MOCK")


@respx.mock
async def test_health_reports_mock(client):
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok", "mock": True}))
    assert (await client.health())["mock"] is True


async def test_mock_server_end_to_end():
    from devtools.mock_urlvet import app as mock_app

    transport = httpx.ASGITransport(app=mock_app)
    c = UrlVetClient("http://mock", transport=transport)
    try:
        risky = await c.analyze("https://gift-claim.example.com")
        assert risky.mock and risky.verdict == "Risky"
        assert (await c.analyze("https://example.com")).verdict == "Safe"
    finally:
        await c.aclose()


async def test_mock_matches_hosts_exactly():
    from devtools.mock_urlvet import app as mock_app

    c = UrlVetClient("http://mock", transport=httpx.ASGITransport(app=mock_app))
    try:
        assert (await c.analyze("https://www.omt.com.lb/")).verdict == "Safe"  # contains "t.co"
        assert (await c.analyze("bit.ly/abc")).verdict == "Suspicious"
    finally:
        await c.aclose()
