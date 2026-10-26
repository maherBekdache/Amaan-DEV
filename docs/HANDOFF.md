# Amaan: project handoff (for the next developer or AI agent)

*Written 24 Oct 2026. Repo: https://github.com/maherBekdache/Amaan-DEV (branch `main`).*
Read this file first, then `docs/DECISIONS.md` (why things are the way they are).

---

## 1. Vision and context
- **Amaan (أمان, "safety")**: an AUB EECE 501 final-year project by a team of 3 students (owner: Maher Bekdache).
- **Goal:** protect Lebanese users from scams in messages, links, QR codes, WhatsApp chats/calls and (later) voice notes, in **Arabic, Arabizi and English**.
- **The product:** the **mobile app** is the end product; it must also work on web and desktop.
- **UX:** drop / paste / scan / share anything, get **Dangerous / Be careful / No warning signs**, plus **why**.
- **Deadline:** demo video by **end of November 2026**.
- **Owner's working style:**
  - wants **brief, precise answers** and step-by-step commands (Windows PowerShell 5.1)
  - wants things **simple and practical**
  - wants to be **asked before hard-to-undo architectural choices**
  - wants each milestone committed

## 2. Hard rules (from the owner, non-negotiable)
1. **Never open, fetch or render an untrusted URL** on the host machine or in our backend. Only URL.vet's containerized headless Chrome (and Lookyloo's sandbox, approved later) touch untrusted destinations. Anything decoded from a QR code is untrusted.
2. **No user content leaves the machine.** No third-party cloud APIs unless the owner approves them.
   - Approved so far: URL.vet; OpenPhish/URLhaus lists; Google Safe Browsing (hash prefixes only); VirusTotal (lookup only); urlscan.io (private scans).
   - Each of these receives **links only**.
   - "Check it yourself" sites receive a link only when the user clicks them.
3. **Every verdict shows its evidence** (which signals fired and why), not just a score. Keep the labels **"automated indicator" / "community report" / "verified"** distinct (UI: *Automated check / Reported by others / Verified*).
4. **Delete temporary uploads after analysis. Keep no logs of message content by default.**

Other standing rules:
- Never put model identifiers in commits or code.
- Commit messages end with the Co-Authored-By / Claude-Session footer used in the history.
- So far everything is pushed **directly to `main`** (the owner's choice).

## 3. Milestones and status
| Milestone | Scope | Status |
|---|---|---|
| M1 | Links + QR (text, drop, upload, webcam), URL.vet, explainable verdict | ✅ done |
| M2 | Lebanese voice-note transcription (Whisper) + anti-spoofing + scam-intent stubs | ❌ not started (owner: "leave model/Whisper/GPU out for now") |
| M3 | WhatsApp: FEASIBILITY.md, Baileys behind a flag, chat-export import, drag-drop matrix doc | ✅ done (the matrix table in `docs/FEASIBILITY.md` must be filled by hand on Windows) |
| + | Cross-platform app (Expo), multi-source check, AI summary + Lookyloo, WhatsApp defaults (unknown numbers), phone WhatsApp tab, "check it yourself" links, testing guide, Word doc | ✅ done (prototype) |
| + | WhatsApp calls (unknown caller, one-ring warning), voice notes via a local speech-to-text hook, AI summary on the phone, mobile permissions research | ✅ done (Oct 26) |

## 4. Architecture
```
 Phone app (Expo: iOS/Android/web/desktop)        Web app (React, served by backend)
   on-device rules (packages/core)                   http://localhost:8000
   sends ONLY links ──► :8001 /gateway/* (token)        │
                              │                         │
                        ┌─────▼─────────────────────────▼──────┐
                        │ Amaan backend (FastAPI, Docker)      │
                        │ extract → local rules → scoring      │
                        │ reputation aggregator, AI, WhatsApp  │
                        └──┬──────────┬──────────┬──────────┬──┘
             URL.vet sandbox    Lookyloo      Ollama (host)   whatsapp-bridge (Node/Baileys)
             (headless Chrome)  (sandbox)     qwen2.5:3b      watches chosen chats, never sends
             + Safe Browsing / VirusTotal / urlscan.io / OpenPhish+URLhaus lists
```

| Part | Path | Tech | Notes |
|---|---|---|---|
| Backend | `backend/amaan/` | Python 3.11, FastAPI, pydantic-settings (`AMAAN_*` env), httpx, OpenCV (WeChat QR) + pyzbar, tldextract, idna | serves API + built web app |
| Web app | `frontend/src/` | React 18, Vite 6, TS, Tailwind 4, jsQR | tabs: Check / WhatsApp / 📱 Phone app |
| Phone/desktop app | `app/` | Expo **SDK 57** (RN 0.86, React 19.2), expo-camera, image-picker, document-picker, file-system, fflate | SDK 57 because App Store Expo Go doesn't support 58 yet |
| Shared core | `packages/core/` | TypeScript (tldts, punycode, fflate) | port of backend rules; **parity-tested** |
| WhatsApp bridge | `whatsapp-bridge/` | Node 22, `baileys` 7.0.0-rc14 (MIT) | compose profile `whatsapp` |
| URL.vet | cloned to `third_party/urlvet` (git-ignored) | Go, Docker (AGPL, unmodified) | pinned `a6b54c29b73a053b916805173fba352e9be0204c` |
| Lookyloo | cloned to `third_party/lookyloo` | Python, Docker (BSD-3, unmodified code) | pinned `a37506c4ffc063464e016ecff8cfa79f7e65461d`; built with `infra/lookyloo/Dockerfile` (adds tzdata) |
| Infra/scripts | `infra/`, `scripts/amaan.ps1`, `scripts/amaan.sh`, `*.bat` | Docker Compose | ports bound to 127.0.0.1 except the phone gateway |

### Backend modules
- `main.py`
  - App, lifespan (UrlVetClient, Reputation, Analyzer, OllamaProvider, LookylooClient) and routes.
  - **guard middleware:** host allowlist (anti DNS-rebinding), size limits, security headers/CSP.
  - `/gateway/*` paths need `Authorization: Bearer <AMAAN_PHONE_TOKEN>` (CORS `*`).
- `analyzer.py`
  - `LinkBudget`; URL.vet and reputation run concurrently.
  - `_finish` builds `Evidence`; each URL item also gets `lookups`.
- `extract/`: `urls.py` (multilingual link finding, defang/refang, punycode), `qr.py`, `payloads.py` (Wi-Fi, SMS, tel, crypto…), `html.py`.
- `scoring/`
  - `local_rules.py`: brand-in-domain, bait domains, userinfo trick, lookalikes, TLDs, hidden characters.
  - `text_cues.py`: weighted phrase cues from `data/cues.json`, Arabizi consonant skeleton, combo "scam script" at weight ≥ 4.
  - `aggregate.py`: levels; an unchecked link is never Low unless *Verified*; ≥ 2 cues + a flagged link → High.
- `reputation/`
  - `feeds.py`: OpenPhish + URLhaus, downloaded every 6 h, checked locally.
  - `safebrowsing.py`: v5 hash prefixes.
  - `virustotal.py`: lookup only, 4/min.
  - `urlscan.py`: private scans.
  - `aggregator.py`.
- `ai/`
  - `provider.py`: Ollama `/api/chat` with a JSON schema.
  - `reasoner.py`: prompt with `<untrusted>` fencing; output `{risk, reasoning, red_flags, advice}`; advisory only.
- `clients/`: `urlvet.py` (`GET /api/v1/analyze?url=`, 20/min), `lookyloo.py` (submit → status → ai_export).
- `api/whatsapp.py`
  - `/import/chat`
  - bridge proxy: `/whatsapp/status, link, logout, chats, selection, alerts`
  - `/whatsapp/ingest` (bridge token; call alerts)
  - `/gateway/whatsapp` (phone)
  - Alerts are kept in RAM only (last 50).
- `importers/whatsapp_export.py`: Android/iOS export parser; zip-bomb guard.
- `lookups.py` + `data/lookups.json`: the 12 "check it yourself" sites.
- `data/brands.json`, `data/cues.json`, `data/lookups.json`: must stay **byte-identical** with `packages/core/src/data/` (a test enforces it).
- `devtools/mock_urlvet.py`: fake URL.vet for laptops without Docker; results are clearly labelled MOCK.

### Phone app (`app/`)
- `App.tsx`:
  - header with connection chip
  - tabs **🔍 Check** (paste, Paste button, 📷 Scan QR, 🖼️ Screenshot) and **💬 WhatsApp**
  - Connect panel (scan or paste `amaan://pair?server=…&token=…`; asks before connecting; warns for non-LAN addresses)
- `src/check.ts`: hybrid flow `analyzeText/analyzeQr → linksToCheck → POST /gateway/analyze/link → mergeServer`, or `markOffline` when unpaired or unreachable.
- `src/server.ts`: pairing (AsyncStorage), `health`, `checkLinks(Batched)`, `whatsappLive`.
- `src/whatsapp.ts`: pick the export, read it in memory, delete the cached file, scan photos for QR codes (temp file deleted), `planChat`, send links (≤ 15) to the server.
- `src/WhatsAppTab.tsx`: chat-check report plus live alerts (polls every 15 s while open).
- `src/ui.tsx`: ResultCard, labels, "Check it yourself" (opens via `Linking.openURL`).
- `src/qrDecoder.web.ts`: web build serves the zxing wasm from `public/`, copied by `postinstall`, instead of a CDN.
- `metro.config.js`: watches `../packages`, alias `@amaan/core`. `tsconfig.json` paths for `@amaan/core`, `tldts`, `fflate`.

### WhatsApp bridge (`whatsapp-bridge/src/`)
- `wa.js`: Baileys socket with a connect guard, a 90 s watchdog, reason-aware reconnects and retry-timer cancel.
  - Never sends: no read receipts, never "online".
  - Handles call offers.
- `chats.js`: watch policy `{mode: "unknown"|"manual", include, exclude}` (default **unknown numbers**); LID↔phone-number id merge; persisted `chats.json` and `selection.json`.
- `extract.js` (what to forward), `server.js` (HTTP API for the backend), `forward.js` (POST to `/whatsapp/ingest` with `AMAAN_BRIDGE_TOKEN`).

## 5. Features (current)
**Checking and verdict**
- Text, links, screenshots, camera QR, dropped HTML / uri-lists, multi-QR images.
- Every reason is labelled; links are defanged and never clickable.
- History is kept in the browser and stores verdicts only.

**Link checks**
- Multi-source: URL.vet + OpenPhish/URLhaus + Safe Browsing + VirusTotal + urlscan.io, with a per-source table.
- **Check it yourself:** 12 clickable rating sites (web, under *Why?*; phone, under each link).

**AI**
- AI summary (what the message is, what each tool found, what to do), with Lookyloo's page capture for links.
- `AMAAN_AI_PROVIDER=ollama` (local demo) or `openai` (any OpenAI-compatible server). A non-local model gets findings only (D17).

**WhatsApp**
- Export import (computer and phone).
- Live watching (unknown numbers and unknown callers by default).
- Calls: alert when an unknown number calls; one-ring warning when it hangs up within 6 s (D18). No call audio exists for linked devices.
- Voice notes: checked through `AMAAN_STT_URL` (a local speech-to-text server); otherwise reported as not checked.
- Alerts on the computer and on the paired phone.

**Phone and desktop app**
- Hybrid on-device analysis, QR pairing, offline fallback.
- WhatsApp tab.
- Web build installable as a desktop app.

**Dev experience**
- One-click `.bat` launchers, mock mode, the `amaan.ps1 test` command, CI (backend, frontend, core, app, bridge, docker).
- `docs/TESTING.md` checklist and `samples/` fake chat exports.

## 6. Setup and commands
**Owner's machine:** Windows, PowerShell 5.1, Docker Desktop, the repo in a folder whose path contains spaces, an iPhone with Expo Go.

| Task | Command |
|---|---|
| Start web app only | `start.bat` → http://localhost:8000 |
| Start + WhatsApp bridge | `start-whatsapp.bat` |
| Start everything (WhatsApp, Lookyloo, phone gateway on LAN :8001) | `start-everything.bat` |
| Stop | `stop.bat` |
| All tests | `.\scripts\amaan.ps1 test` (pytest + frontend typecheck + core vitest) |
| Dev servers (hot reload) | `.\scripts\amaan.ps1 dev` / `dev -Mock` (no Docker; fake URL.vet) |
| Phone app | `cd app; npm ci; npx expo start -c` → scan the QR (iPhone Camera / Expo Go) → in the app **Connect to computer** → scan the code in 📱 Phone app tab |
| Web/desktop app | press `w` in the Expo terminal; pair with **Copy pairing link** |
| macOS/Linux | `./scripts/amaan.sh up|down|test|dev [--mock]` with flags `--whatsapp --lookyloo --phone` |

**Settings** (`.env` at repo root, git-ignored; template `.env.example`):
- Keys: `AMAAN_SAFE_BROWSING_KEY`, `AMAAN_VIRUSTOTAL_KEY`, `AMAAN_URLSCAN_KEY`, `AMAAN_URLHAUS_KEY`, `AMAAN_FEEDS_ENABLED`.
- AI: `AMAAN_AI_MODEL` (default `qwen2.5:3b`), `AMAAN_AI_URL` (`host.docker.internal:11434`).
- Generated by the scripts: `AMAAN_BRIDGE_TOKEN`, `AMAAN_PHONE_URL`, `AMAAN_PHONE_TOKEN`.
- Others: `AMAAN_ALLOWED_HOSTS`, `AMAAN_LOOKYLOO_URL`.

**Ports:**

| Service | Port |
|---|---|
| Amaan | 127.0.0.1:8000 |
| Phone gateway | 0.0.0.0:8001 (`docker-compose.phone.yml`) |
| URL.vet | 127.0.0.1:8080 (network `amaan-urlvet`) |
| Lookyloo | 127.0.0.1:5100 |
| Bridge | 8090 (internal) |
| Ollama | 11434 (host) |
| Expo | 8081 |

**Tests (all passing on 24 Oct):**

| Area | Tests |
|---|---|
| Backend | 164 |
| Core | 34 (parity with backend) |
| Bridge | 19 (`node --test`) |
| App | typecheck + web/iOS/Android bundle export |

## 7. Known pitfalls (learned the hard way)
- **PowerShell 5.1:** native stderr plus `$ErrorActionPreference='Stop'` aborts. Use the `Invoke-Checked` / `Test-Native` helpers in `amaan.ps1`.
- **CRLF:** Git for Windows broke Lookyloo's shebangs. Third-party repos are cloned with `core.autocrlf=false` (`Get-Pinned` / `get_pinned`, auto-repair).
- **Lookyloo** at the pinned commit needs system `tzdata` on Linux (our Dockerfile adds it).
- **Expo:** keep SDK 57 until App Store Expo Go supports 58; use `npm ci` (not `npm install`) so the lockfile isn't rewritten and `git pull` isn't blocked.
- **Cloud dev sandbox:**
  - no Docker daemon, so Docker builds can't be tested there
  - Ollama, the Hugging Face registry and the Expo API are blocked; use `EXPO_OFFLINE=1`
  - `pkill -f` in a compound command kills the shell, so run kills separately
- **Baileys:** don't disable history sync (it breaks sessions); persist chats; merge LID/phone-number ids; one connection at a time.
- Shared data JSONs must stay byte-identical (backend ↔ core).

## 8. Verified vs. not yet verified
**Verified here:**
- all unit tests
- browser end-to-end tests with mock URL.vet: web app; phone app web build (pairing, hybrid check, WhatsApp export with photo QR, live alerts, lookups)

**Verified by the owner on Windows:**
- URL.vet build
- start scripts after the PS 5.1 and CRLF fixes

**Not yet verified:**
- Lookyloo full build after the tzdata fix
- a real Ollama model
- real API keys
- a real Baileys pairing on the newest code
- the phone app on a real iPhone over LAN (Windows firewall on :8001)
- the drag-drop matrix

## 9. Plan / next steps (priority order)
1. **Stabilize for the demo:**
   - owner runs `docs/TESTING.md` end to end
   - fix whatever fails (Lookyloo, Ollama, firewall)
   - fill the drag-drop matrix
   - verify `brands.json`
   - update `docs/DEMO.md` to the 7-minute script (web, WhatsApp live, phone)
2. **Phone polish (small):**
   - per-source table on the phone
   - serve Taha's Lebanese model behind `/v1/audio/transcriptions` and set `AMAAN_STT_URL`
   - Arabic UI / RTL and screen-reader labels
3. **Decision needed from the owner: a standalone phone app.** Either a hosted backend (HTTPS, per-device keys, rate limits; rule 2 approval) or on-device lists plus Safe Browsing from the phone. Then EAS builds: Android APK; iOS via TestFlight ($99 Apple account). Standalone builds also need the iOS local-network permission and Android cleartext settings if LAN pairing stays.
4. **Development build features:**
   - "Share to Amaan" (share sheet)
   - iOS SMS Message Filter extension
   - Android notification listener for unknown WhatsApp numbers
   - call screening / Call Directory
5. **ML (report material):**
   - labelled Lebanese evaluation set (precision/recall per layer)
   - fine-tuned Arabic dialect classifier (MARBERT/CAMeLBERT) → ONNX/TFLite on the phone
   - PhishIntention visual check
   - bigger local model on the owner's GPU
   - optional cloud LLM that receives evidence only (needs approval)
6. **M2 voice notes:** Whisper fine-tuned for Lebanese speech; anti-spoofing and scam-intent stubs; input via the share sheet.

Details: `docs/MOBILE_PERMISSIONS.md`, `docs/FUTURE.md`, `docs/DECISIONS.md` (D1–D18), `docs/FEASIBILITY.md`, `docs/TESTING.md`, `docs/DEVELOPMENT.md`, `docs/Amaan_Documentation.docx`.

## 10. How to work on this repo (for an agent)
- Before changing behavior, check the four hard rules.
- After a change, run:
  - `backend`: `.venv/bin/python -m pytest -q`
  - `packages/core`: `npm test && npm run typecheck`
  - `frontend`: `npm run typecheck && npm run build`
  - `app`: `npx tsc --noEmit` and `EXPO_OFFLINE=1 npx expo export -p web`
  - `whatsapp-bridge`: `node --test`
- If you change a rule in the backend, port it to `packages/core` and extend `test/parity.test.ts`.
- In `app/`, follow `app/AGENTS.md`: use `npx expo install` for native packages, and check the Expo docs for SDK 57.
- Keep the UI simple and the docs short. Give the owner exact commands, not long explanations.
