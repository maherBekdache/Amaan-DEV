"""The expansion worker's findings (sandbox layer L5) become labelled signals."""

import json

import httpx
import pytest

from amaan.clients.expander import ExpanderClient
from amaan.main import app

REPLIES = {
    "http://bit.ly/abc": {"final_url": "https://whsh.money/verify", "stopped": "final page",
                          "hops": [{"url": "http://bit.ly/abc", "status": 301, "via": "http redirect"},
                                   {"url": "https://whsh.money/verify", "status": 200, "via": None}],
                          "title": "Verify", "text": "SECRET PAGE TEXT", "asks_for": ["code", "password"],
                          "human_check": False, "download": None},
    "http://tinyurl.com/app": {"final_url": "https://files.example.com/whish.apk", "stopped": "file download",
                               "hops": [{"url": "http://tinyurl.com/app", "status": 302, "via": "http redirect"},
                                        {"url": "https://files.example.com/whish.apk", "status": 200, "via": None}],
                               "asks_for": [], "human_check": False,
                               "download": {"content_type": "application/vnd.android.package-archive",
                                            "size": 1024, "sha256": "ab" * 32, "filename": "whish.apk"}},
    "http://rb.gy/home": {"final_url": "http://192.168.1.1/", "stopped": "blocked address",
                          "hops": [{"url": "http://rb.gy/home", "status": 302, "via": "http redirect"},
                                   {"url": "http://192.168.1.1/", "status": None, "via": None}],
                          "asks_for": [], "human_check": False, "download": None},
    "http://cutt.ly/x": {"final_url": "https://cutt.ly/x", "stopped": "final page",
                         "hops": [{"url": "http://cutt.ly/x", "status": 200, "via": None}],
                         "asks_for": [], "human_check": True, "download": None},
}


@pytest.fixture
def with_worker(client_off, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=REPLIES[json.loads(request.content)["url"]])

    monkeypatch.setattr(app.state.analyzer, "expander", ExpanderClient("/t.sock", transport=httpx.MockTransport(handler)))
    return client_off


def ids(item):
    return {s["id"] for s in item["signals"]}


def test_redirect_to_typo_site_asking_for_a_code(with_worker):
    ev = with_worker.post("/analyze/text", json={"text": "Your gift: bit.ly/abc"}).json()
    item = ev["items"][0]
    assert {"redirect_typo_domain", "page_asks_code", "page_asks_password", "redirects_elsewhere"} <= ids(item)
    assert item["risk_level"] == "High"
    assert item["expansion"]["final_url"] == "hxxps://whsh[.]money/verify"
    assert "SECRET PAGE TEXT" not in str(ev)  # page text never goes back to the app


def test_app_download_is_dangerous(with_worker):
    item = with_worker.post("/analyze/text", json={"text": "update here tinyurl.com/app"}).json()["items"][0]
    assert "downloads_app" in ids(item) and item["risk_level"] == "High"


def test_private_address_and_human_check(with_worker):
    a = with_worker.post("/analyze/text", json={"text": "rb.gy/home"}).json()["items"][0]
    b = with_worker.post("/analyze/text", json={"text": "cutt.ly/x"}).json()["items"][0]
    assert "redirects_private" in ids(a) and "page_human_check" in ids(b)
    assert b["risk_level"] != "Low"


def test_worker_off_changes_nothing(client_off):
    ev = client_off.post("/analyze/text", json={"text": "bit.ly/abc"}).json()
    assert ev["items"][0]["expansion"] is None
