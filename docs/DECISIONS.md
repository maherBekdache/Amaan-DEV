# Architecture & privacy decisions

Short log of choices that are hard to undo, with who approved them.

## D1. URL.vet runs as a separate, unmodified service
*Approved by the team, Oct 2026 ("do what is more feasible").*

- `scripts/amaan.ps1` / `amaan.sh` clones URL.vet at a **pinned commit** into
  `third_party/urlvet/`, which is git-ignored, so its AGPL-3.0 code never
  enters our repository.
- We do not edit its code. We only add configuration:
  - `server/.env` and `docker/prod/.env`, generated from
    `infra/urlvet/server.env.template` with fresh random secrets;
  - a Compose overlay (`infra/urlvet/docker-compose.amaan.yml`) that binds
    its ports to `127.0.0.1` and joins its backend to the `amaan-urlvet`
    Docker network.
- Amaan talks to it over HTTP only (`GET /api/v1/analyze?url=`).
- We run URL.vet as its own Compose project (`-p urlvet`) rather than with
  Compose `include:`, so our compose file does not depend on its internal
  file layout. `docker compose up` on our side works without it (local rules
  only, clearly marked "incomplete").
- URL.vet allows 20 requests/minute per client and this is hard-coded. We cap
  links per request at 10 and show "rate limited" instead of a verdict.

## D2. Links leave the machine through URL.vet (exception to hard rule 2)
*Approved by the team, Oct 2026.*

Checking a link means something must contact it. URL.vet's container:
- fetches the destination page (HTTP/TLS/DNS) and follows redirects;
- looks up domain registration data (RDAP/WHOIS);
- asks the PhishTank API about the link **only until** PhishTank's
  downloadable list has loaded (normally a few seconds after start), then
  checks it locally.

What never leaves the machine: message text, images, QR images, audio,
history. Only the **link itself** goes to those services, and only after the
user asks for it to be checked.

Kept **off**: Google Safe Browsing / Web Risk, URLhaus and OpenPhish
(opt-in in URL.vet; enabling any of them needs team approval). URL.vet log
files are disabled (`LOG_DIR` empty).

## D3. Short links are never expanded by our code
*Approved by the team, Oct 2026 ("most secure and practical").*

Expanding a short link means requesting it, which is exactly the
"open untrusted URL" that hard rule 1 forbids. Our backend only recognizes
known shorteners (a local list) and flags them. URL.vet follows the chain
inside its container and we show the full chain ("Where it really goes")
from its report. Our HTTP client has `follow_redirects=False` and ignores
system proxy settings.

## D4. One process serves API + UI; camera works on localhost
- The backend serves the built frontend at `http://localhost:8000`, so the
  browser talks to a single origin: no CORS, a strict Content-Security-Policy
  (`connect-src 'self'`, no external images, scripts or frames), and camera
  access works because `localhost` counts as a secure context.
- The Vite dev server (`:5173`) proxies to the backend and is the only extra
  CORS origin.
- Electron later: the build uses relative asset paths and `VITE_API_BASE`.

## D5. History is stored only in the browser, without content
*Approved by the team, Oct 2026.*

`localStorage` holds: time, input type, verdict, item count and up to 5
**defanged host names**. No message text, full URLs, images or QR payloads.
"Clear history" wipes it.

## D6. Uploads never touch disk (or are deleted right away)
- Images are decoded from memory (Pillow -> numpy -> OpenCV/zbar).
- If the multipart parser spools a large upload to a temp file, the endpoint
  closes it in a `finally:` block, which deletes it. In Docker that temp space
  is a `tmpfs` (RAM) and the container filesystem is read-only.
- Bodies larger than the limit are rejected from the `Content-Length` header
  before being read.

## D7. Logging
We log events and counts only. `httpx` request logging is silenced because it
would print the `?url=` being checked. A test asserts that links and message
text never appear in logs.

## D8. Evidence labels
- `automated_indicator`: an algorithm decided (URL.vet checks, Amaan rules,
  keyword cues).
- `community_report`: people reported it (threat lists such as PhishTank,
  via URL.vet).
- `verified`: matched a curated, trusted source. Today that is only
  `backend/amaan/data/brands.json` (official domains). **Each entry must be
  checked by a team member**: a wrong entry would mark a fake site as
  verified.

## D9. Local API hardening
- Ports bound to `127.0.0.1` only (Amaan and URL.vet).
- Host-header allowlist blocks DNS-rebinding attacks from websites in the
  user's browser.
- Container: non-root user, read-only root filesystem, all capabilities
  dropped, `no-new-privileges`.

## D10. WhatsApp: export import by default, Baileys live mode opt-in
*Requested by the team, Oct 2026. Comparison: `FEASIBILITY.md`.*

- Chat-export import (`/import/chat`): processed in memory, nothing kept.
- Live mode: separate `whatsapp-bridge` service (Baileys), started only with
  `start-whatsapp.bat` / the `whatsapp` Compose profile, not published on any host port.
- Default watch mode "unknown numbers": 1:1 chats with numbers not saved in the
  phone's contacts (and unknown callers) are watched automatically; saved
  contacts and groups are not, unless the user ticks them. Mode "only chats I
  pick" is available. Only watched chats are read; only new incoming messages
  and incoming-call notices; never sends, never answers or rejects calls, never
  marks as read, never appears online.
- On disk: the WhatsApp login session, the selected chat ids and the chat list
  (ids + names only, so the picker survives restarts) in the Docker volume
  `wa_session`. "Unlink WhatsApp" deletes all of it and removes the linked device.
- Flagged messages are kept in RAM only (last 50, snippet ≤ 400 characters).
- The bridge must present a random shared secret (`AMAAN_BRIDGE_TOKEN`, generated
  into the git-ignored `.env` by the scripts) to submit messages.
- Unofficial client: **test numbers only** (ban risk), shown in the UI.

## D11. Multi-source link reputation
*Approved by the team, Oct 2026 (all four source types).*

Like VirusTotal/URLVoid: every link goes to several independent sources in
parallel and each answer is shown ("Flagged / Nothing found / No data / Not
set up"). Each source sees **only the link**, never the message or image.

| Source | What leaves the machine | Notes |
|---|---|---|
| OpenPhish list | nothing (list downloaded every 6 h) | research use |
| URLhaus list | nothing (list downloaded) | free abuse.ch Auth-Key |
| Google Safe Browsing v5 | 4-byte hash prefixes only | free key, non-commercial |
| VirusTotal | the link (lookup of existing reports only, never submitted) | 4/min free |
| urlscan.io | the link, scanned remotely as **private** | small free quota |
| URL.vet | the link (our own container) | existing |

Keys live in the git-ignored `.env`. Missing keys simply skip that source.
Reported-by-people lists are labelled *Reported by others*; engine verdicts
*Automated check*. Hosts where anyone can publish (Google Sites, GitHub
Pages, …) are never flagged as a whole because of one listed page.

## D12. AI second opinion: local model now, cloud later
*Approved by the team, Oct 2026.*

- Local LLM via Ollama (default `qwen2.5:3b`); nothing leaves the computer.
- Shown as an advisory "AI second opinion" next to the evidence-based verdict, never
  replacing it. Scam text/pages are fenced as untrusted data; output is a fixed JSON
  schema, validated and clipped.
- Lookyloo (optional, `start-everything.bat`) opens the first link in its sandbox and
  gives the AI the redirect chain and page text. Lookyloo runs private: captures not
  listed, internal addresses refused, all third-party modules off, captures archived
  after 7 days (`infra/lookyloo/`).
- A cloud model may replace Ollama later through `ai/provider.py`; that needs a new
  decision because content would leave the machine (see FUTURE.md §1).

## D13. One cross-platform app: React Native + Expo, hybrid checking
*Approved by the team, Oct 2026.*

- **Framework:** React Native + Expo (`app/`): one TypeScript code base for iOS,
  Android and web; desktop = the web build installed from Chrome/Edge (an Electron
  or Tauri wrapper can be added later if a store app is needed). Chosen over Flutter
  because the team and the existing web UI are already React/TypeScript, and the
  analysis code can be shared.
- **Hybrid:** the phone runs the same rules as the server (`packages/core`, a
  TypeScript port of `backend/amaan` kept identical by parity tests: same examples,
  same `brands.json` / `cues.json`). Messages, QR contents and images never leave
  the phone. Only the links found are sent to the paired computer, which checks them
  in URL.vet and the reputation sources (D2, D11).
- **Pairing:** the computer exposes only `/gateway/health` and
  `/gateway/analyze/link` on the local network (port 8001, `start-everything.bat` /
  `-Phone`), each call needing a random 256-bit token. The token reaches the phone
  through a QR on the laptop screen (`amaan://pair?...`); the app asks before
  connecting and warns if the address is outside the local network.
- **Offline / unpaired:** the app still gives a verdict; links are marked
  *not checked online* and are never shown as safe.
- The app never opens a checked link: links are shown defanged and are not tappable.

## Open items for the team
- [ ] Verify every official domain in `backend/amaan/data/brands.json`.
- [ ] Decide on Lookyloo "deep inspect" (see `LINK_TOOLS_COMPARISON.md`).
- [ ] Decide whether a PhishIntention spike fits the ML part of the report.
