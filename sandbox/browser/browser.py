"""Amaan browser sandbox (layer L6 of the link check, docs/LINK_SECURITY.md).

L5 (sandbox/expander) reads pages without running them. Scam pages that only appear
once their scripts run, or only to a phone that moves and taps (cloaking), need a real
browser. This worker opens ONE link in a fresh headless Chromium with a phone profile,
lets the scripts run, imitates a person (scroll, tap, wait), then reports what it saw:

- every address the page went through, including script and meta redirects;
- the last page's title, visible text, and the fields it asks for (password, code, card);
- login forms inside frames from another site, and drawn "browser windows" that show a
  fake address bar (browser-in-the-browser);
- text the page tries to put in the clipboard (paste-and-run "ClickFix" lures);
- CAPTCHAs in front of the page; downloads (hashed, never opened or kept);
- a small screenshot, so the user can see what the page looks like.

Disposable: the worker serves a single link and then exits; Docker starts a fresh
container (read-only image, empty /tmp) for the next one, so nothing a page leaves behind
(cookies, cache, service workers, a compromised process) reaches the next check.
It runs on the internal sandbox network; its only way out is the egress proxy, and it
answers the Amaan backend over a Unix socket. Nothing about the link is logged.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit

log = logging.getLogger("amaan.browser")

PROXY = os.environ.get("AMAAN_EGRESS_PROXY", "http://egress:3128")
SOCKET = os.environ.get("AMAAN_BROWSER_SOCKET", "/run/amaan-browser/browser.sock")
JOBS_PER_LIFE = int(os.environ.get("AMAAN_BROWSER_JOBS_PER_LIFE", "1"))  # 0 = no limit (tests)
CHROME_SANDBOX = os.environ.get("AMAAN_BROWSER_CHROME_SANDBOX", "auto")  # auto | on | off
LOAD_TIMEOUT_MS = 15000
TOTAL_TIMEOUT_S = 30.0
TEXT_LIMIT = 4000
DOWNLOAD_LIMIT = 50 * 1024 * 1024
REQUEST_LIMIT = 8 * 1024

# A mid-range Android phone in Lebanon. Scale 1 keeps the screenshot small.
PHONE = {
    "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Mobile Safari/537.36",
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 1,
    "is_mobile": True,
    "has_touch": True,
    "locale": "ar-LB",
    "timezone_id": "Asia/Beirut",
    "extra_http_headers": {"Accept-Language": "ar-LB,ar;q=0.9,en;q=0.8,fr;q=0.7"},
}

# Runs in every page before its own scripts: notes clipboard writes and pop-up windows.
WATCH = """
(() => {
  const log = { clip: [], popups: 0 };
  Object.defineProperty(window, '__amaan', { value: log, enumerable: false });
  const note = (t) => { if (typeof t === 'string' && t.trim()) log.clip.push(t.slice(0, 500)); };
  try {
    const c = navigator.clipboard;
    if (c && c.writeText) { const w = c.writeText.bind(c); c.writeText = (t) => { note(t); return w(t).catch(() => {}); }; }
    if (c && c.write) { const w2 = c.write.bind(c); c.write = (items) => { note('[clipboard item]'); return w2(items).catch(() => {}); }; }
  } catch (e) {}
  const exec = document.execCommand.bind(document);
  document.execCommand = (cmd, ...rest) => {
    if (String(cmd).toLowerCase() === 'copy') {
      const a = document.activeElement;
      note((a && 'value' in a && a.value) || String(window.getSelection() || ''));
    }
    return exec(cmd, ...rest);
  };
  document.addEventListener('copy', (e) => {
    try { setTimeout(() => note(e.clipboardData && e.clipboardData.getData('text/plain')), 0); } catch (x) {}
  }, true);
  const open = window.open;
  window.open = (...a) => { log.popups += 1; return null; };
})();
"""

# Reads the page once it has settled. Runs in the main frame only.
INSPECT = r"""
() => {
  const seen = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const fields = [...document.querySelectorAll('input, textarea, select')].filter(seen).map(i => ({
    type: (i.getAttribute('type') || '').toLowerCase(), name: i.name || '', id: i.id || '',
    placeholder: i.getAttribute('placeholder') || '', autocomplete: i.getAttribute('autocomplete') || '',
    inputmode: i.getAttribute('inputmode') || '', label: (i.labels && i.labels[0] ? i.labels[0].innerText : '').slice(0, 80) }));
  // Drawn browser windows: a positioned box that shows an address as plain text and holds a login.
  const fake = [];
  for (const el of document.querySelectorAll('div, span, p, input[readonly]')) {
    const t = (el.value || el.childElementCount === 0 && el.textContent || '').trim();
    if (!/^(https?:\/\/)?[a-z0-9-]+(\.[a-z0-9-]+)+(\/\S*)?$/i.test(t) || t.length > 120) continue;
    let box = el.parentElement, depth = 0;
    while (box && depth < 8) {
      const pos = getComputedStyle(box).position;
      if ((pos === 'fixed' || pos === 'absolute') &&
          box.querySelector('input[type=password], iframe')) { fake.push(t); break; }
      box = box.parentElement; depth += 1;
    }
  }
  const frames = [...document.querySelectorAll('iframe')].filter(seen).map(f => f.src || '').filter(Boolean);
  const forms = [...document.querySelectorAll('form')].map(f => f.action || '').filter(Boolean);
  return { title: document.title || '', text: (document.body ? document.body.innerText : '').slice(0, 20000),
           fields, fake: [...new Set(fake)].slice(0, 3), frames: frames.slice(0, 10), forms: forms.slice(0, 10),
           clip: (window.__amaan && window.__amaan.clip) || [], popups: (window.__amaan && window.__amaan.popups) || 0 };
}
"""

CODE_FIELD = re.compile(r"otp|one.?time|verif|\bcode\b|_code|code_|pin\b|passcode|sms|رمز|كود|التحقق", re.IGNORECASE)
CARD_FIELD = re.compile(r"card|cc-?(?:number|num|exp|csc)|cvv|cvc|expir|iban|بطاقة", re.IGNORECASE)
HUMAN_CHECK = re.compile(r"recaptcha|turnstile|hcaptcha|challenges\.cloudflare\.com|arkoselabs|funcaptcha", re.IGNORECASE)
# Paste-and-run lures: a command in the clipboard, or instructions to open the Run box / a terminal.
COMMAND = re.compile(r"powershell|pwsh|mshta|cmd(?:\.exe)?\s*/c|rundll32|regsvr32|certutil|bitsadmin|curl\s|wget\s|"
                     r"iex\b|invoke-|frombase64|\|\s*(?:ba)?sh\b|osascript|msiexec", re.IGNORECASE)
RUN_STEPS = re.compile(r"(win(?:dows)?\s*(?:key)?\s*\+\s*r\b|⊞|ctrl\s*\+\s*v.*enter|press\s+enter|run\s+dialog|"
                       r"terminal|cmd\b|powershell)", re.IGNORECASE)


def asks_for(fields: list[dict[str, str]]) -> list[str]:
    found: list[str] = []
    for f in fields:
        words = " ".join(f.values())
        kind = f.get("type", "")
        if kind == "password" and "password" not in found:
            found.append("password")
        one_time = f.get("autocomplete") == "one-time-code"
        if (one_time or (kind not in ("hidden", "submit", "button") and CODE_FIELD.search(words))) and "code" not in found:
            found.append("code")
        if CARD_FIELD.search(words) and kind != "hidden" and "card" not in found:
            found.append("card")
    return found


def _web(url: str) -> bool:
    return urlsplit(url).scheme.lower() in ("http", "https")


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


async def _behave_like_a_person(page) -> None:
    """Cloaking kits wait for touches, scrolling or time before showing the scam."""
    with contextlib.suppress(Exception):
        await page.mouse.move(120, 300, steps=8)
        await page.mouse.move(260, 520, steps=12)
        await page.touchscreen.tap(195, 420)
        await page.mouse.wheel(0, 600)
        await page.wait_for_timeout(700)
        await page.mouse.wheel(0, -600)


async def _launch(pw, proxy: str, sandbox: str):
    """Chromium with its own sandbox when the container allows it (needs user namespaces)."""
    opts = {"headless": True, "proxy": {"server": proxy, "bypass": "<-loopback>"},
            "args": ["--disable-dev-shm-usage", "--no-first-run", "--disable-background-networking",
                     "--disable-sync", "--metrics-recording-only", "--disable-component-update"]}
    if sandbox in ("on", "auto"):
        try:
            return await pw.chromium.launch(chromium_sandbox=True, **opts), True
        except Exception:  # no user namespaces here: fall back, and say so
            if sandbox == "on":
                raise
    return await pw.chromium.launch(chromium_sandbox=False, **opts), False


async def render(url: str, proxy: str = PROXY, sandbox: str = CHROME_SANDBOX) -> dict:
    """Open `url` in a fresh browser through the egress proxy. Never raises."""
    from playwright.async_api import Error as PwError
    from playwright.async_api import async_playwright

    t0 = time.monotonic()
    out: dict = {"ok": True, "hops": [], "final_url": url, "stopped": "final page", "title": "", "text": "",
                 "asks_for": [], "human_check": False, "clipboard": [], "clickfix": False, "fake_window": [],
                 "login_frames": [], "popups": 0, "download": None, "screenshot": "", "chrome_sandbox": None}
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", url, re.IGNORECASE):
        if re.match(r"^[a-z][a-z0-9+.\-]*:(?!\d)", url, re.IGNORECASE):
            return {**out, "ok": False, "stopped": "not a web link", "elapsed_ms": 0}
        url = "http://" + url
    if not _web(url):
        return {**out, "ok": False, "stopped": "not a web link", "elapsed_ms": 0}

    hops: list[dict] = []
    blocked = False

    def on_response(resp) -> None:
        nonlocal blocked
        req = resp.request
        if req.frame != page.main_frame or not req.is_navigation_request():
            return
        if resp.headers.get("x-amaan-egress") == "blocked":
            blocked = True
        via = "http redirect" if 300 <= resp.status < 400 else None
        if hops and hops[-1]["via"] is None and hops[-1]["url"] != resp.url:
            hops[-1]["via"] = "script or meta redirect"
        hops.append({"url": resp.url, "status": resp.status, "via": via})

    async with async_playwright() as pw:
        try:
            browser, out["chrome_sandbox"] = await _launch(pw, proxy, sandbox)
        except Exception as e:  # noqa: BLE001
            return {**out, "ok": False, "stopped": "browser did not start", "message": str(e)[:200],
                    "elapsed_ms": int((time.monotonic() - t0) * 1000)}
        try:
            ctx = await browser.new_context(accept_downloads=True, service_workers="block", java_script_enabled=True,
                                            bypass_csp=False, **PHONE)
            await ctx.add_init_script(WATCH)
            page = await ctx.new_page()
            page.on("response", on_response)
            page.on("popup", lambda p: asyncio.ensure_future(p.close()))
            downloads: list = []
            page.on("download", lambda d: downloads.append(d))
            try:
                await page.goto(url, wait_until="load", timeout=LOAD_TIMEOUT_MS)
            except PwError as e:
                msg = str(e)
                if "Download is starting" in msg or "ERR_ABORTED" in msg:  # the link is a file, not a page
                    for _ in range(30):
                        if downloads:
                            break
                        await page.wait_for_timeout(100)
                if downloads:
                    pass
                elif "ERR_TUNNEL_CONNECTION_FAILED" in msg or "ERR_PROXY" in msg or blocked:
                    out["stopped"] = "blocked address" if blocked or "TUNNEL" in msg else "could not connect"
                elif "Timeout" in msg:
                    out["stopped"] = "took too long"
                else:
                    out["stopped"] = "could not connect"
            if out["stopped"] == "final page" and not downloads:
                with contextlib.suppress(PwError):
                    await page.wait_for_load_state("networkidle", timeout=4000)
                await _behave_like_a_person(page)
                with contextlib.suppress(PwError):
                    await page.wait_for_load_state("networkidle", timeout=3000)
                await page.wait_for_timeout(500)
            if blocked:
                out["stopped"] = "blocked address"
            if downloads:
                d = downloads[0]
                digest, size = hashlib.sha256(), 0
                with contextlib.suppress(Exception):
                    path = await d.path()
                    with open(path, "rb") as f:
                        while chunk := f.read(65536):
                            digest.update(chunk)
                            size += len(chunk)
                            if size >= DOWNLOAD_LIMIT:
                                break
                    os.unlink(path)
                name = d.suggested_filename or urlsplit(d.url).path.rsplit("/", 1)[-1]
                out["download"] = {"content_type": "", "size": size, "sha256": digest.hexdigest(), "filename": name[:120],
                                   "complete": size < DOWNLOAD_LIMIT}
                out["stopped"] = "file download"
            elif out["stopped"] == "final page":
                info = await page.evaluate(INSPECT)
                out["final_url"] = page.url
                out["title"] = " ".join(info["title"].split())[:200]
                text = " ".join(info["text"].split())
                out["text"] = text[:TEXT_LIMIT]
                out["asks_for"] = asks_for(info["fields"])
                frame_urls = [f.url for f in page.frames[1:]]
                out["human_check"] = any(HUMAN_CHECK.search(u) for u in frame_urls + info["frames"])
                site = _host(page.url)
                for f in page.frames[1:]:
                    fh = _host(f.url)
                    if not fh or fh == site or HUMAN_CHECK.search(f.url):
                        continue
                    with contextlib.suppress(PwError):
                        if await f.locator("input[type=password]").count():
                            out["login_frames"].append(fh)
                out["fake_window"] = info["fake"]
                out["popups"] = info["popups"]
                out["clipboard"] = [c[:300] for c in info["clip"]][:3]
                out["clickfix"] = any(COMMAND.search(c) for c in info["clip"]) or (
                    bool(info["clip"]) and bool(RUN_STEPS.search(text)))
                with contextlib.suppress(PwError):
                    shot = await page.screenshot(type="jpeg", quality=45, timeout=5000)
                    out["screenshot"] = "data:image/jpeg;base64," + base64.b64encode(shot).decode()
            if hops:
                out["final_url"] = out["final_url"] if out["stopped"] == "final page" else hops[-1]["url"]
            out["hops"] = hops[:15] or [{"url": url, "status": None, "via": None}]
        except Exception as e:  # noqa: BLE001 - a hostile page must never crash the worker silently
            out.update(ok=False, stopped="browser error", message=str(e)[:200])
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
    out["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return out


# --- Unix socket server: GET /health, POST /render ------------------------------------

def _reply(writer: asyncio.StreamWriter, status: str, body: dict) -> None:
    data = json.dumps(body, ensure_ascii=False).encode()
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
                 f"Connection: close\r\n\r\n".encode() + data)


class Worker:
    def __init__(self, proxy: str = PROXY, jobs_per_life: int = JOBS_PER_LIFE, sandbox: str = CHROME_SANDBOX) -> None:
        self.proxy, self.jobs_left, self.sandbox = proxy, jobs_per_life, sandbox
        self.lock = asyncio.Lock()
        self.done = asyncio.Event()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        last = False
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            first, *lines = head.decode("latin-1").split("\r\n")
            method, path, _ = first.split(" ", 2)
            length = next((int(x.split(":", 1)[1]) for x in lines if x.lower().startswith("content-length:")), 0)
            if method == "GET" and path == "/health":
                _reply(writer, "200 OK", {"status": "ok"})
            elif method == "POST" and path == "/render" and 0 < length <= REQUEST_LIMIT:
                body = json.loads(await asyncio.wait_for(reader.readexactly(length), 5))
                url = str(body.get("url", ""))[:4096]
                async with self.lock:  # one page at a time per container
                    if self.done.is_set():
                        _reply(writer, "503 Service Unavailable", {"ok": False, "stopped": "restarting"})
                    else:
                        try:
                            result = await asyncio.wait_for(render(url, self.proxy, self.sandbox), TOTAL_TIMEOUT_S + 15)
                        except TimeoutError:
                            result = {"ok": False, "stopped": "took too long"}
                        _reply(writer, "200 OK", result)
                        if self.jobs_left > 0:
                            self.jobs_left -= 1
                            last = self.jobs_left == 0
            else:
                _reply(writer, "400 Bad Request", {"error": "POST /render {\"url\": ...} or GET /health"})
        except Exception:  # noqa: BLE001
            _reply(writer, "400 Bad Request", {"error": "bad request"})
        try:
            await writer.drain()
        finally:
            writer.close()
            if last:
                self.done.set()  # disposable: this container's single link is done


async def serve(path: str = SOCKET, worker: Worker | None = None) -> tuple[asyncio.base_events.Server, Worker]:
    worker = worker or Worker()
    if os.path.exists(path):
        os.unlink(path)
    server = await asyncio.start_unix_server(worker.handle, path=path, limit=REQUEST_LIMIT * 2)
    os.chmod(path, 0o660)
    return server, worker


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server, worker = await serve()
    log.info("browser sandbox ready (one link per container)" if worker.jobs_left == 1 else "browser sandbox ready")
    async with server:
        await worker.done.wait()
        server.close()
        with contextlib.suppress(OSError):
            os.unlink(SOCKET)
    log.info("link done; exiting so Docker starts a clean container")


if __name__ == "__main__":
    asyncio.run(main())
