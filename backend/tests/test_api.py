import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from amaan.config import get_settings
from amaan.main import app
from tests.conftest import to_bytes

URLVET = get_settings().urlvet_base_url


def report(verdict: str, score: int, listed: bool = False) -> dict:
    return {"threat_feeds": {"listed": listed, "sources": ["PhishTank"] if listed else []},
            "result": {"verdict": verdict, "final_score": score, "trust_score": score, "risk_score": 100 - score,
                       "reasons": {"bad_reasons": ["New domain."] if verdict != "Safe" else None,
                                   "good_reasons": ["Old domain."] if verdict == "Safe" else None}}}


@pytest.fixture
def client():
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        with TestClient(app) as c:
            c.mock = mock
            yield c


def urlvet_returns(client, mapping: dict[str, dict]):
    def handler(request: httpx.Request):
        target = request.url.params["url"]
        for key, body in mapping.items():
            if key in target:
                return httpx.Response(200, json=body)
        return httpx.Response(200, json=report("Safe", 90))

    client.mock.get(f"{URLVET}/api/v1/analyze").mock(side_effect=handler)


def test_health(client):
    client.mock.get(f"{URLVET}/health").mock(return_value=httpx.Response(200))
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["urlvet"]["reachable"] is True
    assert body["qr_decoders"]["opencv"] is True
    assert r.headers["cache-control"] == "no-store"


def test_text_end_to_end(client):
    urlvet_returns(client, {"omt-lb.xyz": report("Risky", 8, listed=True)})
    r = client.post("/analyze/text", json={"text": "مبروك! ربحت جائزة من OMT، ادخل على omt-lb.xyz/claim وابعتلي الكود"})
    assert r.status_code == 200
    ev = r.json()
    assert ev["risk_level"] == "High"
    assert ev["complete"] is True
    item = ev["items"][0]
    assert item["display"] == "omt-lb[.]xyz/claim"
    assert item["urlvet"]["verdict"] == "Risky"
    labels = {s["label"] for s in item["signals"]}
    assert {"community_report", "automated_indicator"} <= labels
    assert any(s["id"] == "cue_asks_for_code" for s in ev["signals"])
    assert "reported" in ev["explanation"]


def test_text_safe(client):
    urlvet_returns(client, {})
    ev = client.post("/analyze/text", json={"text": "meeting notes at https://example.com/doc"}).json()
    assert ev["risk_level"] == "Low"


def test_text_urlvet_down_is_not_low(client):
    client.mock.get(f"{URLVET}/api/v1/analyze").mock(side_effect=httpx.ConnectError("refused"))
    ev = client.post("/analyze/text", json={"text": "https://example.com"}).json()
    assert ev["risk_level"] == "Medium"
    assert ev["complete"] is False
    assert any("not running" in w for w in ev["warnings"])


def test_html_and_uri_list(client):
    urlvet_returns(client, {})
    html = '<p>Login: <a href="https://evil-login.net/x">https://www.blombank.com</a></p><img src="https://tracker-pixel.net/p.gif">'
    ev = client.post("/analyze/text", json={"html": html, "uri_list": "# comment\nhttps://bit.ly/abc\n"}).json()
    displays = [i["display"] for i in ev["items"]]
    assert "hxxps://bit[.]ly/abc" in displays
    assert "hxxps://evil-login[.]net/x" in displays
    evil = next(i for i in ev["items"] if "evil" in i["display"])
    assert evil["risk_level"] == "High"
    assert any(s["id"] == "link_text_mismatch" for s in evil["signals"])
    assert not any("tracker" in d for d in displays)  # <img> is never treated as content


def test_text_empty(client):
    assert client.post("/analyze/text", json={"text": "  "}).status_code == 400


def test_text_without_links(client):
    ev = client.post("/analyze/text", json={"text": "kifak? bokra mnetla2a"}).json()
    assert ev["items"] == [] and ev["risk_level"] == "Low"
    assert "No links" in ev["explanation"]


def test_url_limit(client):
    urlvet_returns(client, {})
    text = " ".join(f"site{i}.com" for i in range(14))
    ev = client.post("/analyze/text", json={"text": text}).json()
    skipped = [i for i in ev["items"] if i["urlvet"]["status"] == "skipped"]
    assert len(skipped) == 4 and ev["warnings"]


def test_image_end_to_end(client, multi_qr_png):
    urlvet_returns(client, {"phish-login.net": report("Suspicious", 40)})
    data = multi_qr_png("https://phish-login.net/login", "WIFI:S:FreeNet;T:nopass;;")
    r = client.post("/analyze/image", files={"file": ("qr.png", data, "image/png")})
    assert r.status_code == 200
    ev = r.json()
    assert ev["input_type"] == "image" and ev["stats"]["qr_codes"] == 2
    kinds = {i["kind"]: i for i in ev["items"]}
    assert kinds["url"]["risk_level"] == "Medium"
    assert kinds["wifi"]["details"]["password"] == "none"
    assert kinds["wifi"]["urlvet"] is None  # non-URL payloads never go to URL.vet


def test_camera_source(client, qr_png):
    urlvet_returns(client, {})
    r = client.post("/analyze/image", files={"file": ("f.png", qr_png("tel:+96170000000"), "image/png")},
                    data={"source": "camera"})
    ev = r.json()
    assert ev["input_type"] == "camera"
    assert ev["items"][0]["kind"] == "tel"


def test_image_without_qr(client):
    from PIL import Image

    r = client.post("/analyze/image", files={"file": ("x.png", to_bytes(Image.new("RGB", (50, 50), "white")), "image/png")})
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["warnings"]


def test_image_bad_file(client):
    r = client.post("/analyze/image", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 415


def test_image_too_large(client):
    big = b"0" * (get_settings().max_upload_bytes + 10)
    r = client.post("/analyze/image", files={"file": ("x.png", big, "image/png")})
    assert r.status_code == 413


def test_rejects_foreign_host(client):
    r = client.get("/health", headers={"host": "evil-login.net"})
    assert r.status_code == 400


def test_cors_blocks_random_site(client):
    r = client.options("/analyze/text", headers={"origin": "https://evil-login.net",
                                                 "access-control-request-method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_no_link_content_in_logs(client, caplog):
    import logging

    urlvet_returns(client, {})
    with caplog.at_level(logging.DEBUG):
        client.post("/analyze/text", json={"text": "secret-message https://private-link-123.com/token"})
    assert "private-link-123" not in caplog.text
    assert "secret-message" not in caplog.text
