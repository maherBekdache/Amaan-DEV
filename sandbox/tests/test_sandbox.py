"""Tests for the egress proxy and the expansion worker, run as plain processes
against a small web server on this machine (no Docker, no internet).

Run with the backend's environment:  backend/.venv/bin/python -m pytest sandbox/tests
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

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "egress"), str(Path(__file__).resolve().parents[1] / "expander")]
import egress
import expander

APK = b"PK\x03\x04 not a real app" * 100

PAGES = {
    "/start": (302, {"Location": "/meta"}, b""),
    "/meta": (200, {"Content-Type": "text/html"},
              b"<html><head><meta http-equiv='refresh' content='0; url=/js'></head></html>"),
    "/js": (200, {"Content-Type": "text/html"},
            b"<html><body><script>window.location.href = '/final';</script></body></html>"),
    "/final": (200, {"Content-Type": "text/html; charset=utf-8"},
               "<html><head><title>Whish Money | Verify</title></head><body><h1>Confirm your account</h1>"
               "<script>var secret = 1;</script><form><input name='phone' placeholder='Phone'>"
               "<input type='password' name='pass'><input name='otp_code' autocomplete='one-time-code'></form>"
               "<p>أدخل رمز التحقق</p></body></html>".encode()),
    "/app.apk": (200, {"Content-Type": "application/vnd.android.package-archive"}, APK),
    "/captcha": (200, {"Content-Type": "text/html"},
                 b"<html><body><div class='cf-turnstile' data-sitekey='x'></div><p>Checking your browser</p></body></html>"),
    "/empty": (200, {}, b""),
    "/missing.apk": (404, {"Content-Type": "application/octet-stream"}, b"gone"),
    "/loop": (302, {"Location": "/loop2"}, b""),
    "/loop2": (302, {"Location": "/loop"}, b""),
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


async def start_proxy(policy: egress.Policy) -> tuple[asyncio.base_events.Server, str]:
    server = await egress.serve("127.0.0.1", 0, policy)
    return server, f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


# --- the egress proxy -------------------------------------------------------------

@pytest.mark.parametrize("ip,ok", [
    ("8.8.8.8", True), ("2001:4860:4860::8888", True),
    ("10.0.0.1", False), ("172.16.5.4", False), ("192.168.1.1", False), ("127.0.0.1", False),
    ("169.254.169.254", False), ("100.64.1.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("::1", False), ("fc00::1", False), ("fe80::1", False), ("::ffff:10.0.0.1", False), ("::ffff:192.168.0.1", False),
    ("2002:c0a8:0101::1", False), ("not-an-ip", False),
])
def test_only_public_addresses(ip, ok):
    assert egress.public_address(ip) is ok


async def test_proxy_refuses_local_and_private_destinations(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port})))
    async with server, httpx.AsyncClient(proxy=proxy, trust_env=False) as c:
        r = await c.get(base + "/final")  # plain http through the proxy
        assert r.status_code == 403 and r.headers["x-amaan-egress"] == "blocked"
        r = await c.get(f"http://localhost:{port}/final")  # a name that resolves locally
        assert r.status_code == 403
        with pytest.raises(httpx.ProxyError):  # https (CONNECT) to a private address
            await c.get("https://10.0.0.1/")


async def test_proxy_refuses_other_ports(site):
    base, _ = site
    server, proxy = await start_proxy(egress.Policy(address_ok=lambda ip: True))  # ports 80/443 only
    async with server, httpx.AsyncClient(proxy=proxy, trust_env=False) as c:
        r = await c.get(base + "/final")
        assert r.status_code == 403


async def test_proxy_forwards_allowed_traffic(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    async with server, httpx.AsyncClient(proxy=proxy, trust_env=False) as c:
        r = await c.get(base + "/final")
        assert r.status_code == 200 and "Whish Money" in r.text


# --- the expansion worker ---------------------------------------------------------

async def test_follows_every_kind_of_redirect_and_reads_the_page(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    async with server:
        out = await expander.expand(base + "/start", proxy)
    assert [h["via"] for h in out["hops"]] == ["http redirect", "meta refresh", "script (read, not run)", None]
    assert out["final_url"] == base + "/final"
    assert out["stopped"] == "final page"
    assert out["title"] == "Whish Money | Verify"
    assert "Confirm your account" in out["text"] and "secret" not in out["text"]
    assert out["asks_for"] == ["password", "code"]
    assert out["download"] is None


async def test_downloads_are_hashed_not_kept(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    async with server:
        out = await expander.expand(base + "/app.apk", proxy)
    assert out["stopped"] == "file download"
    assert out["download"]["sha256"] == hashlib.sha256(APK).hexdigest()
    assert out["download"]["content_type"] == "application/vnd.android.package-archive"
    assert out["download"]["filename"] == "app.apk"


async def test_empty_or_error_answer_is_not_a_download(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    async with server:
        empty = await expander.expand(base + "/empty", proxy)
        missing = await expander.expand(base + "/missing.apk", proxy)
    assert empty["download"] is None and empty["stopped"] == "empty answer"
    assert missing["download"] is None and missing["stopped"] == "error 404"


async def test_human_check_and_loops(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    async with server:
        assert (await expander.expand(base + "/captcha", proxy))["human_check"] is True
        assert (await expander.expand(base + "/loop", proxy))["stopped"] == "redirect loop"


async def test_private_address_is_reported_as_blocked(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port})))  # default address rule
    async with server:
        out = await expander.expand(base + "/start", proxy)
    assert out["stopped"] == "blocked address"


async def test_not_a_web_link():
    out = await expander.expand("javascript:alert(1)", "http://127.0.0.1:9")
    assert out["ok"] is False and out["stopped"] == "not a web link"


async def test_unix_socket_endpoint(site, tmp_path):
    base, port = site
    proxy_server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    sock = str(tmp_path / "expander.sock")
    worker = await expander.serve(sock, proxy)
    async with proxy_server, worker:
        transport = httpx.AsyncHTTPTransport(uds=sock)
        async with httpx.AsyncClient(transport=transport, base_url="http://expander") as c:
            assert (await c.get("/health")).json() == {"status": "ok"}
            r = await c.post("/expand", json={"url": base + "/start"})
            assert r.json()["final_url"] == base + "/final"
            assert (await c.post("/nope", json={})).status_code == 400


async def test_link_without_scheme_is_tried_as_http(site):
    base, port = site
    server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    async with server:
        out = await expander.expand(base.removeprefix("http://") + "/start", proxy)
    assert out["final_url"] == base + "/final"


# --- end to end: Amaan's backend client -> worker (Unix socket) -> egress proxy -> site ---

async def test_backend_client_end_to_end(site, tmp_path):
    from amaan.clients.expander import ExpanderClient
    from amaan.extract.urls import defang
    from amaan.scoring.aggregate import expansion_signals

    base, port = site
    proxy_server, proxy = await start_proxy(egress.Policy(ports=frozenset({port}), address_ok=lambda ip: True))
    sock = str(tmp_path / "expander.sock")
    worker = await expander.serve(sock, proxy)
    async with proxy_server, worker:
        client = ExpanderClient(sock)
        assert await client.reachable()
        exp = await client.expand(base + "/start")
    assert exp.status == "ok" and exp.final_url == defang(base + "/final")  # links reach the app defanged
    assert [h.via for h in exp.hops][:3] == ["http redirect", "meta refresh", "script (read, not run)"]
    assert "Confirm your account" in exp.text  # kept for the AI summary only
    assert "text" not in exp.model_dump()  # never sent to the app
    ids = {s.id for s in expansion_signals(exp, base + "/start")}
    assert {"page_asks_code", "page_asks_password"} <= ids


async def test_backend_client_when_worker_is_down(tmp_path):
    from amaan.clients.expander import ExpanderClient

    exp = await ExpanderClient(str(tmp_path / "missing.sock")).expand("https://example.com/")
    assert exp.status == "unavailable" and exp.hops == []
