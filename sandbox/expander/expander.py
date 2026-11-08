"""Amaan expansion worker (layer L5 of the link check, docs/LINK_SECURITY.md).

Opens an untrusted link the way a phone would, but without a browser: it follows
redirects one hop at a time (HTTP, <meta refresh>, and simple script redirects
that are READ, never run), then reads the last page's title, visible text and
form fields. A file download is hashed (SHA-256) and thrown away, never opened.

It runs in its own container on an internal network whose only way out is the
egress proxy (sandbox/egress), and it answers the Amaan backend over a Unix
socket in a shared volume, so it cannot open a connection to the backend.
Nothing is written to disk and nothing about the link is logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

log = logging.getLogger("amaan.expander")

PROXY = os.environ.get("AMAAN_EGRESS_PROXY", "http://egress:3128")
SOCKET = os.environ.get("AMAAN_EXPANDER_SOCKET", "/run/amaan-expander/expander.sock")
MAX_HOPS = 10
HOP_TIMEOUT_S = 5.0
TOTAL_TIMEOUT_S = 20.0
HTML_LIMIT = 512 * 1024  # bytes of a page that are read
DOWNLOAD_LIMIT = 50 * 1024 * 1024  # bytes of a file that are hashed
TEXT_LIMIT = 4000  # characters of page text kept for the AI summary
MAX_JOBS = 4
REQUEST_LIMIT = 8 * 1024

# An ordinary Android phone, Lebanese languages: cloaking kits often hide the scam
# from desktop browsers and from crawlers that announce themselves.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar-LB,ar;q=0.9,en;q=0.8,fr;q=0.7",
}
HTML_TYPES = {"text/html", "application/xhtml+xml"}
SCRIPT_REDIRECT = re.compile(
    r"""(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=\s*["']([^"']{1,2000})["']"""
    r"""|location\.(?:replace|assign)\(\s*["']([^"']{1,2000})["']\s*\)""")
CODE_FIELD = re.compile(r"otp|one.?time|verif|\bcode\b|_code|code_|pin\b|passcode|sms|رمز|كود|التحقق", re.IGNORECASE)
CARD_FIELD = re.compile(r"card|cc-?(?:number|num|exp|csc)|cvv|cvc|expir|iban", re.IGNORECASE)
HUMAN_CHECK = re.compile(r"g-recaptcha|cf-turnstile|h-captcha|hcaptcha|challenges\.cloudflare\.com|recaptcha/api", re.IGNORECASE)


class PageReader(HTMLParser):
    """Title, visible text, form fields, meta refresh and script redirect targets."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text: list[str] = []
        self.inputs: list[dict[str, str]] = []
        self.refresh: str | None = None
        self.scripts: list[str] = []
        self.human_check = False
        self._skip = 0
        self._in_title = False
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        joined = " ".join(a.values())
        if HUMAN_CHECK.search(joined):
            self.human_check = True
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
            self._in_script = tag == "script"
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", a.get("content", ""), re.IGNORECASE)
            if m and self.refresh is None:
                self.refresh = m.group(1).strip()
        elif tag in ("input", "textarea", "select"):
            self.inputs.append({k: a.get(k, "") for k in ("type", "name", "id", "placeholder", "autocomplete")})

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
            self._in_script = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts.append(data[:20000])
            if HUMAN_CHECK.search(data):
                self.human_check = True
        elif self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.text.append(" ".join(data.split()))


def asks_for(inputs: list[dict[str, str]]) -> list[str]:
    found: list[str] = []
    for i in inputs:
        words = " ".join(i.values())
        kind = i.get("type", "").lower()
        if kind == "password" and "password" not in found:
            found.append("password")
        one_time = i.get("autocomplete") == "one-time-code"
        if (one_time or (kind not in ("hidden", "submit", "button") and CODE_FIELD.search(words))) and "code" not in found:
            found.append("code")
        if CARD_FIELD.search(words) and kind != "hidden" and "card" not in found:
            found.append("card")
    return found


def script_target(scripts: list[str]) -> str | None:
    for s in scripts:
        m = SCRIPT_REDIRECT.search(s)
        if m:
            return (m.group(1) or m.group(2)).strip()
    return None


def _web(url: str) -> bool:
    return urlsplit(url).scheme.lower() in ("http", "https")


async def expand(url: str, proxy: str = PROXY) -> dict:
    """Follow `url` hop by hop through the egress proxy. Never raises."""
    t0 = time.monotonic()
    out: dict = {"ok": True, "hops": [], "final_url": url, "stopped": "final page", "title": "", "text": "",
                 "asks_for": [], "human_check": False, "download": None}
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", url, re.IGNORECASE):
        if re.match(r"^[a-z][a-z0-9+.\-]*:(?!\d)", url, re.IGNORECASE):  # javascript:, data:, tel:, intent: ...
            return {**out, "ok": False, "stopped": "not a web link"}
        url = "http://" + url  # "bit.ly/x": the browser would try http first
    if not _web(url):
        return {**out, "ok": False, "stopped": "not a web link"}
    seen: set[str] = set()
    current = url
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=False, timeout=HOP_TIMEOUT_S, headers=HEADERS,
                                 trust_env=False) as client:
        for _ in range(MAX_HOPS + 1):
            if time.monotonic() - t0 > TOTAL_TIMEOUT_S:
                out["stopped"] = "took too long"
                break
            if current in seen:
                out["stopped"] = "redirect loop"
                break
            seen.add(current)
            if not _web(current):
                out["hops"].append({"url": current, "status": None, "via": "leaves the web"})
                out["stopped"] = "not a web link"
                break
            client.cookies.clear()  # no cookies carried between pages
            try:
                async with client.stream("GET", current) as r:
                    hop = {"url": current, "status": r.status_code, "via": None}
                    out["hops"].append(hop)
                    out["final_url"] = current
                    if r.headers.get("x-amaan-egress") == "blocked":
                        out["stopped"] = "blocked address"
                        break
                    location = r.headers.get("location")
                    if 300 <= r.status_code < 400 and location:
                        hop["via"] = "http redirect"
                        current = urljoin(current, location.strip())
                        continue
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    disposition = r.headers.get("content-disposition", "").lower()
                    if ctype in HTML_TYPES and "attachment" not in disposition:
                        body = b""
                        async for chunk in r.aiter_bytes():
                            body += chunk
                            if len(body) >= HTML_LIMIT:
                                break
                        page = PageReader()
                        try:
                            page.feed(body[:HTML_LIMIT].decode(r.encoding or "utf-8", errors="replace"))
                        except Exception:  # noqa: BLE001, S110 - broken HTML is normal on scam pages
                            pass
                        text = " ".join(page.text)
                        nxt = page.refresh or (script_target(page.scripts) if len(text) < 300 else None)
                        if nxt:
                            hop["via"] = "meta refresh" if page.refresh else "script (read, not run)"
                            current = urljoin(current, nxt)
                            continue
                        out.update(title=" ".join(page.title.split())[:200], text=text[:TEXT_LIMIT],
                                   asks_for=asks_for(page.inputs), human_check=page.human_check)
                        break
                    # Anything else is a file: hash it, keep nothing.
                    digest, size = hashlib.sha256(), 0
                    async for chunk in r.aiter_bytes():
                        digest.update(chunk)
                        size += len(chunk)
                        if size >= DOWNLOAD_LIMIT:
                            break
                    if size == 0 or not 200 <= r.status_code < 300:  # an empty or error answer is not a download
                        out["stopped"] = "empty answer" if size == 0 else f"error {r.status_code}"
                        break
                    name = re.search(r"filename\*?=(?:utf-8'')?\"?([^\";]+)", disposition)
                    out["download"] = {"content_type": ctype, "size": size, "sha256": digest.hexdigest(),
                                       "complete": size < DOWNLOAD_LIMIT,
                                       "filename": (name.group(1) if name else urlsplit(current).path.rsplit("/", 1)[-1])[:120]}
                    out["stopped"] = "file download"
                    break
            except httpx.ProxyError as e:
                out["hops"].append({"url": current, "status": None, "via": None})
                out["stopped"] = "blocked address" if "403" in str(e) else "could not connect"
                break
            except httpx.TimeoutException:
                out["hops"].append({"url": current, "status": None, "via": None})
                out["stopped"] = "took too long"
                break
            except httpx.InvalidURL:
                out["hops"].append({"url": current, "status": None, "via": None})
                out["stopped"] = "not a web link"
                break
            except httpx.HTTPError:
                out["hops"].append({"url": current, "status": None, "via": None})
                out["stopped"] = "could not connect"
                break
        else:
            out["stopped"] = "too many redirects"
    out["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return out


# --- a tiny HTTP server on a Unix socket (one endpoint) -----------------------------

def _reply(writer: asyncio.StreamWriter, status: str, body: dict) -> None:
    data = json.dumps(body, ensure_ascii=False).encode()
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
                 f"Connection: close\r\n\r\n".encode() + data)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, jobs: asyncio.Semaphore,
                  proxy: str) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        first, *lines = head.decode("latin-1").split("\r\n")
        method, path, _ = first.split(" ", 2)
        length = 0
        for line in lines:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1])
        if method == "GET" and path == "/health":
            _reply(writer, "200 OK", {"status": "ok"})
        elif method == "POST" and path == "/expand" and 0 < length <= REQUEST_LIMIT:
            body = json.loads(await asyncio.wait_for(reader.readexactly(length), 5))
            url = str(body.get("url", ""))[:4096]
            async with jobs:
                result = await asyncio.wait_for(expand(url, proxy), TOTAL_TIMEOUT_S + 10)
            _reply(writer, "200 OK", result)
        else:
            _reply(writer, "400 Bad Request", {"error": "POST /expand {\"url\": ...} or GET /health"})
    except TimeoutError:
        _reply(writer, "504 Gateway Timeout", {"ok": False, "stopped": "took too long"})
    except Exception:  # noqa: BLE001 - any malformed request gets the same answer
        _reply(writer, "400 Bad Request", {"error": "bad request"})
    try:
        await writer.drain()
    finally:
        writer.close()


async def serve(path: str = SOCKET, proxy: str = PROXY) -> asyncio.base_events.Server:
    if os.path.exists(path):
        os.unlink(path)
    jobs = asyncio.Semaphore(MAX_JOBS)
    server = await asyncio.start_unix_server(lambda r, w: _handle(r, w, jobs, proxy), path=path, limit=REQUEST_LIMIT * 2)
    os.chmod(path, 0o660)  # the shared volume is mounted only by this worker and the Amaan backend
    return server


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = await serve()
    log.info("expansion worker ready")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
