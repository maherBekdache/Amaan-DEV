"""Layer L6 in the backend: when the browser sandbox is used, and what its findings become."""

from __future__ import annotations

import httpx

from amaan.clients.browser import BrowserClient
from amaan.schemas import BrowserView, Expansion, ExpansionHop
from amaan.scoring import aggregate


def exp(**kw) -> Expansion:
    base = dict(status="ok", stopped="final page", hops=[ExpansionHop(url="hxxp://pay-check[.]example/x", status=200)],
                raw_hops=["http://pay-check.example/x"], text="x" * 400)
    return Expansion(**{**base, **kw})


def view(**kw) -> BrowserView:
    base = dict(status="ok", stopped="final page", hops=[ExpansionHop(url="hxxp://pay-check[.]example/x", status=200)],
                raw_hops=["http://pay-check.example/x"])
    return BrowserView(**{**base, **kw})


def ids(signals) -> set[str]:
    return {s.id for s in signals}


def test_when_the_browser_is_needed():
    url = "http://pay-check.example/x"
    assert not aggregate.needs_browser(exp(), url, suspicious=False)  # a full, readable page: L5 is enough
    assert aggregate.needs_browser(exp(), url, suspicious=True)
    assert aggregate.needs_browser(exp(text=""), url, False)  # empty shell built by scripts
    assert aggregate.needs_browser(exp(human_check=True), url, False)
    assert aggregate.needs_browser(exp(hops=[ExpansionHop(url="a", via="script (read, not run)"),
                                             ExpansionHop(url="b")]), url, False)
    assert not aggregate.needs_browser(exp(stopped="blocked address", text=""), url, True)
    assert not aggregate.needs_browser(exp(text="", raw_hops=["https://whish.money/"]), "https://whish.money/", True)
    assert not aggregate.needs_browser(Expansion(status="unavailable"), url, True)
    assert not aggregate.needs_browser(None, url, True)


def test_browser_findings_become_signals():
    url = "http://pay-check.example/x"
    s = aggregate.browser_signals(view(clickfix=True, fake_window=["hxxps://accounts[.]google[.]com"],
                                       login_frames=["evil-relay.example"], asks_for=["code"],
                                       title="Whish Money | Verify"), exp(text=""), url)
    assert {"page_paste_command", "page_fake_window", "page_login_frame", "page_hidden_from_scanners",
            "page_asks_code", "page_brand_mismatch"} <= ids(s)
    assert all(x.source == "browser" and x.label.value == "automated_indicator" for x in s)
    by = {x.id: x.severity.value for x in s}
    assert by["page_paste_command"] == by["page_fake_window"] == by["page_brand_mismatch"] == "high"


def test_browser_does_not_repeat_what_l5_reported():
    url = "http://pay-check.example/x"
    s = aggregate.browser_signals(view(asks_for=["password"]), exp(asks_for=["password"]), url)
    assert ids(s) == set()


def test_official_site_and_failed_browser_are_quiet():
    official = view(asks_for=["password"], title="Whish Money", raw_hops=["https://whish.money/login"],
                    fake_window=["x"], login_frames=["y"])
    assert ids(aggregate.browser_signals(official, exp(text=""), "https://whish.money/login")) == set()
    assert aggregate.browser_signals(BrowserView(status="unavailable"), exp(), "http://a.example") == []


def test_brand_named_in_title():
    assert aggregate.brand_on_page("Whish Money | Verify") == ("Whish Money", "whish.money")
    assert aggregate.brand_on_page("OMT - تحويل") == ("OMT", "omt.com.lb")
    assert aggregate.brand_on_page("Sign in with your Apple ID")[0] == "Apple"
    for title in ("Apple pie recipes", "Keep in touch", "Format your document", "Bakery", "alfa romeo club"):
        assert aggregate.brand_on_page(title) is None, title


def test_l5_reports_brand_mismatch_too():
    s = aggregate.expansion_signals(exp(title="BLOM Bank eBanking", asks_for=["password"]), "http://pay-check.example/x")
    assert "page_brand_mismatch" in ids(s)
    s = aggregate.expansion_signals(exp(title="BLOM Bank news"), "http://pay-check.example/x")  # asks for nothing
    assert "page_brand_mismatch" not in ids(s)


async def test_client_waits_for_the_next_container_and_hides_the_clipboard():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(503, json={"ok": False, "stopped": "restarting"})
        return httpx.Response(200, json={
            "ok": True, "hops": [{"url": "http://a.example/", "status": 200, "via": None}], "final_url": "http://a.example/",
            "stopped": "final page", "title": "T", "text": "body", "asks_for": ["code", "nonsense"], "clickfix": True,
            "clipboard": ["powershell -c bad"], "fake_window": ["https://accounts.google.com"],
            "screenshot": "data:image/jpeg;base64,AAAA", "chrome_sandbox": False, "elapsed_ms": 5})

    c = BrowserClient("/nowhere.sock", transport=httpx.MockTransport(handler), wait_s=5)
    v = await c.render("http://a.example/")
    assert len(calls) == 2 and v.status == "ok" and v.asks_for == ["code"] and v.clickfix and v.copies_text
    assert v.hops[0].url == "hxxp://a[.]example/" and v.fake_window == ["hxxps://accounts[.]google[.]com"]
    sent = v.model_dump()
    assert "clipboard" not in sent and "text" not in sent and sent["screenshot"].startswith("data:image/jpeg")
    assert (await c.render("http://a.example/")).title == "T" and len(calls) == 2  # cached
    assert c.cached("http://a.example/").text == "body"
    await c.aclose()


async def test_client_when_the_sandbox_is_off():
    def down(request):
        raise httpx.ConnectError("no socket")

    c = BrowserClient("/nowhere.sock", transport=httpx.MockTransport(down), wait_s=0.2)
    assert (await c.render("http://a.example/")).status == "unavailable"
    assert (await BrowserClient(None).render("http://a.example/")).status == "unavailable"
    await c.aclose()
