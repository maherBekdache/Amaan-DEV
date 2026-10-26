# Developer guide

## Install (once)
Everything in the README, plus:
- [Python 3.11](https://www.python.org/downloads/release/python-3119/) (tick *Add to PATH*)
- [Node.js 22 LTS](https://nodejs.org/)

## Commands
Windows (PowerShell, in the repo folder; first run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`):

| Command | What it does |
|---|---|
| `.\scripts\amaan.ps1 test` | backend pytest + web app type check + phone rules (`packages/core`), ~1 min |
| `.\scripts\amaan.ps1 dev` | live-reload dev servers → http://localhost:5173 (start Docker with `start.bat` once first) |
| `.\scripts\amaan.ps1 dev -Mock` | same, without Docker: **fake** link verdicts, pink "MOCK" label |
| `.\scripts\amaan.ps1 up` / `down` / `status` / `logs` | full stack (what `start.bat` / `stop.bat` call) |
| `.\scripts\amaan.ps1 up -WhatsApp` | full stack + WhatsApp bridge (what `start-whatsapp.bat` calls) |
| `.\scripts\amaan.ps1 up -Phone` | full stack + the phone link gateway on port 8001 |
| `cd app; npx expo start` | phone app dev server (Expo Go on the phone, `w` for web) |
| `cd app; npx tsc --noEmit` | phone app type check |
| `cd packages\core; npm test` | on-device rules: parity tests against the backend examples |
| `cd whatsapp-bridge; npm test` | WhatsApp bridge tests |

macOS / Linux / WSL: `./scripts/amaan.sh test | dev [--mock] | up | down | status | logs`.

GitHub runs the same tests on every pull request (`.github/workflows/ci.yml`).

No Docker? `dev -Mock` runs everything except the link sandbox (fake, clearly labelled verdicts).

## Manual test checklist (before a demo or a big merge)
Full step-by-step guide for every feature: [TESTING.md](TESTING.md). Short version:
- [ ] Each **Try an example** button gives the expected result
- [ ] Paste text with Ctrl+V outside the text box, then drag a screenshot from File Explorer
- [ ] Camera: show `frontend/public/examples/03-open-wifi.png` on your phone
- [ ] Stop URL.vet (`docker compose -p urlvet stop backend`): link results say "Be careful" plus a warning, never "No warning signs"
- [ ] Links in results are defanged (`hxxps://…[.]…`) and not clickable

## Project layout
```
backend/amaan/       FastAPI app (main.py: routes + request guard; analyzer.py: one analysis)
  extract/           find links in text, decode QR codes, parse dropped HTML (all offline)
  scoring/           local rules, Arabic/Arabizi scam phrases, final verdict + reasons
  reputation/        OpenPhish/URLhaus lists, Safe Browsing, VirusTotal, urlscan.io
  clients/           URL.vet sandbox, Lookyloo, speech-to-text for voice notes
  ai/                AI summary (Ollama or any OpenAI-compatible server)
  api/whatsapp.py, importers/   WhatsApp: chat-export import, alerts, bridge proxy
  data/              brands.json (official domains, each checked by a teammate), cues.json, lookups.json
backend/tests/       pytest suite (incl. every built-in example)
backend/devtools/    fake URL.vet for -Mock
frontend/src/        web app (App.tsx, components/, lib/api.ts)
frontend/src/examples.json + public/examples/   built-in examples (regenerate: scripts/make_examples.py)
app/                 phone app (Expo): App.tsx screens, src/check.ts (hybrid flow), src/server.ts (pairing)
packages/core/       on-device analysis shared by the apps (TypeScript port of backend/amaan, parity-tested)
whatsapp-bridge/     optional Node service (Baileys) for live WhatsApp
samples/             fake WhatsApp chat exports for testing
infra/               config for URL.vet and Lookyloo (their code is cloned, unmodified, into third_party/)
scripts/             amaan.ps1 / amaan.sh
```

## API (http://localhost:8000/api/docs)
| Endpoint | Body |
|---|---|
| `POST /analyze/text` | JSON `{text, html?, uri_list?}` |
| `POST /analyze/image` | multipart `file` (PNG/JPG/WebP), optional `source=camera` |
| `GET /health` | status, URL.vet reachable, QR decoders |
| `POST /import/chat` | multipart `file` (WhatsApp export .txt/.zip) |
| `GET /gateway/health`, `POST /gateway/analyze/link`, `GET /gateway/whatsapp` | phone app only: `Authorization: Bearer <pairing token>`; link check takes JSON `{urls}` (max 10) |
| `GET /whatsapp/status`, `POST /whatsapp/link`, `GET /whatsapp/chats`, `PUT /whatsapp/selection`, `GET /whatsapp/alerts` | live WhatsApp (bridge must run) |

Every analysis returns the same Evidence object: `risk_level`, `explanation`,
`items[]` (each with `signals[]`, URL.vet result), message-level `signals[]`
and `warnings[]`. Every signal has a `label`: `automated_indicator`,
`community_report` or `verified`.

## Settings (environment variables)
Every setting is an `AMAAN_*` variable; the full list with defaults is `backend/amaan/config.py`.
API keys go in `.env` (template: `.env.example`).

## Troubleshooting
| Problem | Fix |
|---|---|
| `start.bat` says Docker is not running | open Docker Desktop, wait for *Engine running* |
| Status says "Link checker starting…" | wait a minute; still there? `docker compose -p urlvet logs backend` |
| `429 Too Many Requests` while building | Docker Hub limit: wait 10 min or `docker login` |
| Port 8000 in use | `stop.bat`, close other servers |
| Camera doesn't start | use `http://localhost:8000` and allow the camera in the address bar |
| Phone app: "Can't reach the computer" | same Wi-Fi (not AUB's: use a hotspot), allow port 8001 in Windows firewall, started with `start-everything.bat` |
| Expo Go: "incompatible SDK" | update Expo Go from the store (the app uses Expo SDK 57, the one the App Store Expo Go runs; move to 58 once Expo Go supports it) |
| Phone can't load the app from `expo start` | `npx expo start --tunnel` (sends only the app's code through Expo's tunnel, not your data) |
