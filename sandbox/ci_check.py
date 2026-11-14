"""Checks the running link sandbox (run after `scripts/amaan.sh up`; used by CI).

1. Amaan's health reports the expansion worker as reachable.
2. A real link goes through the whole chain: Amaan -> worker (Unix socket) -> egress -> internet.
3. The worker cannot reach private addresses through the proxy, nor the internet without it.
4. URL.vet's Chrome (its screenshot endpoint) works through the proxy and cannot reach
   private addresses; its network has no direct route out.
5. The browser sandbox (L6) opens a page, is replaced by a fresh container, and has no
   direct route out.
6. With --runtime runsc, the sandbox containers really run under gVisor.

Only harmless public pages are used (example.com).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import httpx

AMAAN = "http://localhost:8000"
URLVET = "http://localhost:8080"
BROWSER_NET = "amaan-urlvet-browser"
CURL = "curlimages/curl:8.11.1"
PROXY = "http://10.213.47.200:3128"  # fixed address of the egress proxy on the sandbox network
failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail != "" else ""), flush=True)
    if not ok:
        failures.append(name)


def run(*cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)


def in_worker(code: str) -> subprocess.CompletedProcess[str]:
    return run("docker", "compose", "exec", "-T", "expander", "python", "-c", code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default="runc")
    runtime = ap.parse_args().runtime

    for _ in range(60):
        try:
            health = httpx.get(f"{AMAAN}/health", timeout=5).json()
            if (health.get("expander") or {}).get("reachable") and (health.get("browser") or {}).get("reachable"):
                break
        except (httpx.HTTPError, ValueError) as e:
            health = {"error": repr(e)}
        time.sleep(2)
    check("health: expansion worker reachable", health.get("expander") == {"enabled": True, "reachable": True},
          health)

    ev = httpx.post(f"{AMAAN}/analyze/text", json={"text": "Look: https://example.com/"}, timeout=90).json()
    item = next(i for i in ev["items"] if i["kind"] == "url")
    exp = item.get("expansion") or {}
    check("worker followed a public link", exp.get("status") == "ok" and exp.get("stopped") == "final page",
          {k: exp.get(k) for k in ("status", "stopped", "final_url", "title")})
    check("URL.vet answered", (item.get("urlvet") or {}).get("status") == "ok", (item.get("urlvet") or {}).get("status"))

    # Layer L6: example.com has too little text for L5, so the browser sandbox opens it too.
    check("health: browser sandbox reachable", (health.get("browser") or {}).get("reachable") is True,
          health.get("browser"))
    view = item.get("browser") or {}
    check("browser sandbox opened the page", view.get("status") == "ok" and view.get("title") == "Example Domain"
          and str(view.get("screenshot", "")).startswith("data:image/jpeg"),
          {k: view.get(k) for k in ("status", "stopped", "title", "chrome_sandbox", "elapsed_ms")})
    box = run("docker", "compose", "ps", "-aq", "browser").stdout.strip()
    for _ in range(30):  # disposable: the container that opened the page must have been replaced
        restarts = run("docker", "inspect", "-f", "{{.RestartCount}}", box).stdout.strip()
        if restarts.isdigit() and int(restarts) >= 1:
            break
        time.sleep(1)
    check("browser container was replaced after its link", restarts.isdigit() and int(restarts) >= 1, restarts)
    for _ in range(30):
        try:
            again = httpx.get(f"{AMAAN}/health", timeout=5).json().get("browser") or {}
            if again.get("reachable"):
                break
        except (httpx.HTTPError, ValueError):
            again = {}
        time.sleep(1)
    check("a fresh browser container is ready again", again.get("reachable") is True, again)
    r = run("docker", "compose", "exec", "-T", "browser", "python", "-c",
            "import urllib.request;urllib.request.urlopen('http://example.com',timeout=8)")
    check("browser container has no direct route out", r.returncode != 0, r.stderr.strip().splitlines()[-1:])

    ev = httpx.post(f"{AMAAN}/analyze/text", json={"text": "Router: http://192.168.1.1/login"}, timeout=90).json()
    uv = ev["items"][0].get("urlvet") or {}
    check("private address not sent to URL.vet", uv.get("status") == "skipped", uv.get("message"))

    r = in_worker(f"import httpx;print(httpx.get('http://192.168.1.1',proxy='{PROXY}',timeout=10).status_code)")
    check("worker -> proxy -> 192.168.1.1 refused (403)", r.stdout.strip() == "403", r.stdout.strip() or r.stderr[-200:])
    r = in_worker(f"import httpx;print(httpx.get('http://169.254.169.254/',proxy='{PROXY}',timeout=10).status_code)")
    check("worker -> proxy -> cloud metadata refused (403)", r.stdout.strip() == "403", r.stdout.strip() or r.stderr[-200:])
    r = in_worker("import httpx;httpx.get('http://example.com',timeout=8)")
    check("worker has no direct route out", r.returncode != 0, r.stderr.strip().splitlines()[-1:] if r.stderr else "")

    shot = httpx.get(f"{URLVET}/api/v1/screenshot", params={"url": "https://example.com/"}, timeout=90)
    check("URL.vet Chrome screenshot through the proxy", shot.status_code == 200
          and shot.headers.get("content-type", "").startswith("image/"), shot.status_code)
    r = run("docker", "run", "--rm", "--network", BROWSER_NET, CURL, "-sS", "-m", "8", "-o", "/dev/null",
            "-w", "%{http_code}", "-x", "http://10.213.48.200:3128", "http://192.168.1.1/")
    check("browser network -> proxy -> 192.168.1.1 refused (403)", r.stdout.strip() == "403", r.stdout.strip())
    r = run("docker", "run", "--rm", "--network", BROWSER_NET, CURL, "-sS", "-m", "8", "-o", "/dev/null",
            "http://example.com/")
    check("browser network has no direct route out", r.returncode != 0, r.stderr.strip()[-120:])

    if runtime != "runc":
        worker = run("docker", "compose", "ps", "-q", "expander").stdout.strip()
        for name in (worker, box, "urlvet-chrome"):
            r = run("docker", "inspect", "-f", "{{.Name}} {{.HostConfig.Runtime}}", name)
            check(f"runs under {runtime}", r.stdout.strip().endswith(" " + runtime), r.stdout.strip() or r.stderr.strip())

    print(json.dumps({"failed": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
