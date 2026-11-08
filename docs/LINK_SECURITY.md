# Link security and sandbox

*8 Nov 2026. Decision record: DECISIONS.md D19. Research and full design: the team document
"Amaan Link Security and Sandbox Design".*

## 1. Problems found and what was done

| # | Problem (review of 8 Nov) | Status |
|---|---|---|
| 1 | **Typing errors missed.** Lookalike checks compared letter shapes only, so `whsh.money` or `whihs.money` passed. | Fixed: `typo_domain` rule (keyboard slips of a brand name, 5+ letters). |
| 2 | **Open redirects inherited trust.** `google.com/url?q=<scam>` got *Verified* because the outer domain is official, and the inner link was never checked. | Fixed: inner links (`?url=`, `?q=`, `?u=`, Google AMP) become their own items; an official link that forwards elsewhere is no longer *Verified* (`hidden_redirect`). |
| 3 | **Browsers on open networks.** URL.vet's headless Chrome had full LAN and internet access, so a page could reach the user's router or home network. Lookyloo's browser sat on the Docker network shared with the Amaan backend. (The design document first said URL.vet's Chrome shared the backend's network; that was Lookyloo.) | Fixed: Chrome moved to an internal network behind the egress proxy; Lookyloo removed. |
| 4 | **Shared kernel.** Containers share the host kernel; runc escapes still occur (CVE-2024-21626). | Reduced: optional gVisor (`AMAAN_SANDBOX_RUNTIME=runsc`); Firecracker planned for spring. |
| 5 | **One scanner identity.** One desktop profile and one IP address, which cloaking kits filter. | Partly: the expansion worker uses an Android phone profile and Lebanese languages. One IP remains (section 7). |
| 6 | **Chrome sandbox flag unverified.** | Checked: URL.vet's image runs Chrome as root with `--no-sandbox`. Kept (the image needs it), compensated by the container, the internal network and gVisor. |
| 7 | **Link key bug** (found while fixing 2): the duplicate check cut a link at its *last* `://`, so an outer link and its inner link counted as one. | Fixed in backend and `packages/core`; test added. |
| 8 | **Parity gap:** `packages/core` lacked the `whatsapp_chat_link` rule the backend had. | Fixed. |

## 2. How a link is checked

```
Phone / web app          Amaan backend (no network to the link)          Sandbox (internal networks)
L1 intake ── link ──► L2 gateway ─► L3 static rules ──────────────┐
                                 ├► L4 reputation (lists, APIs) ──┤
                                 └► L5 expansion worker ──────────┤   via Unix socket (one way)
                                    URL.vet (Chrome)  ────────────┤   both leave only through
                                                                  ▼   the egress proxy
                                                    L7 verdict ─► L8 AI summary ─► reply
```

| Layer | Runs on | Receives | Sends on | Never sees |
|---|---|---|---|---|
| L1 Intake | phone or browser | message, screenshot, QR | normalised links only (phone); the backend for the web app | n/a |
| L2 Gateway | backend | link, pairing token | link to L3, L4, L5 | logs counts only |
| L3 Static rules | backend, no network | link | signals, inner links | the page |
| L4 Reputation | backend to listed services | link or hash | one labelled result per source | the page |
| L5 Expansion worker | sandbox container | link | hops, final link, title, form fields asked, download hash, up to 4,000 characters of text (text for L8 only) | the message, the backend |
| URL.vet | its own containers | link | score, reasons, redirect chain | the message |
| L6 Browser sandbox | planned (spring) | last link | screenshot, script behaviour | the message |
| L7 Verdict | backend | all signals | level and labelled reasons | n/a |
| L8 AI summary | local model | evidence, fenced page text | plain summary; cannot change the verdict | the message, unless the model is local |

Every new domain the worker finds on the way goes back through the L3 rules (`redirect_<rule>`).

## 3. New signals (all *Automated check*)

| Signal | Level | Example |
|---|---|---|
| `typo_domain` | high | `whsh.money` (letter left out) |
| `brand_prefix` | high | `whish.money.example.com` |
| `brand_other_ending` | medium | `whish.com` for `whish.money` |
| `hidden_redirect` | medium | `google.com/url?q=https://...` |
| `redirect_typo_domain`, `redirect_lookalike_domain`, ... | as the rule | a short link that lands on a typo domain |
| `redirects_private` | medium | a link that tries to reach `192.168.1.1` |
| `page_asks_code` | high | the last page asks for an SMS or WhatsApp code |
| `page_asks_password`, `page_asks_card` | medium | password or card fields on a non-official site |
| `page_human_check` | medium | CAPTCHA in front of the page (hides it from scanners) |
| `downloads_app`, `downloads_program` | high | the link downloads an APK or a program |

## 4. The sandbox

- **Expansion worker** (`sandbox/expander`): follows HTTP redirects, meta refresh and simple script
  redirects (read, never run). Limits: 10 hops, 5 s per hop, 20 s total, 512 KB of HTML, 50 MB hashed
  for downloads, 4 jobs at once. No disk, no browser, no logs of links. Container: read-only, all
  capabilities dropped, no-new-privileges, 256 MB, half a CPU, 64 processes.
- **Egress proxy** (`sandbox/egress`): ports 80 and 443 to public addresses only. Refuses private
  ranges, loopback, link-local (cloud metadata), carrier-grade NAT, multicast, local IPv6 and IPv6
  tunnels that wrap private IPv4. It resolves the name itself and connects to the checked address
  (no DNS rebinding). Logs counts only.
- **One-way channel:** the backend calls the worker over a Unix socket in a shared volume; the worker
  has no network route to the backend.
- **URL.vet:** its Chrome is on `amaan-urlvet-browser` (internal); a second proxy copy is its only way out.

## 5. Tests

- `sandbox/tests` (27): address rules, proxy refusals, every redirect type, downloads, CAPTCHA, loops,
  the Unix socket. They run without Docker or internet.
- `backend/tests/test_link_rules.py`, `test_expansion.py`, and 23 shared cases in
  `backend/tests/data/link_cases.json`, also run by `packages/core/test/parity.test.ts`.
- Manual checks on Windows: TESTING.md section 4.

## 6. Optional: gVisor

gVisor gives each sandbox container its own user-space kernel. It needs Linux.
- **Linux or WSL2 Ubuntu with Docker Engine** (not Docker Desktop), following gvisor.dev:
  ```bash
  curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
  sudo apt-get update && sudo apt-get install -y runsc
  sudo runsc install && sudo systemctl restart docker
  ```
  Then `AMAAN_SANDBOX_RUNTIME=runsc` in `.env` and restart Amaan.
- **Docker Desktop on Windows:** not supported out of the box (its engine runs in a VM we cannot add
  runtimes to reliably). Keep `runc` for the demo. Not yet tried on the owner's machine.

## 7. Known limits

- URL.vet's Chrome runs with `--no-sandbox` (its image runs as root).
- URL.vet's own Go backend fetches the link for TLS and DNS data without our proxy; it stays on
  URL.vet's network, which can reach the LAN. Fixing it needs URL.vet changes or a firewall rule.
- All checks leave from one IP address, so IP-based cloaking still works. A Lebanese or residential
  exit costs money beyond the \$200 budget.
- Pages that only show the scam after scripts run look empty to the worker until L6 exists.
- `brand_other_ending` can flag a brand's real second domain (for example a bank's `.com` and
  `.com.lb`) until `brands.json` lists it.
- The "Misspelled site" example (`whsh.money`) is sent to URL.vet and the worker like any link.
  Whether that domain is registered has not been checked; check it before the demo and swap it for
  another misspelling if it hosts a live site.
- The sandbox images were validated with `docker compose config` only; the build and run on Windows
  are not yet verified.
