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
| `.\scripts\amaan.ps1 test` | all automated tests (backend pytest + frontend type check), ~30 s |
| `.\scripts\amaan.ps1 dev` | live-reload dev servers → http://localhost:5173 (start Docker with `start.bat` once first) |
| `.\scripts\amaan.ps1 dev -Mock` | same, without Docker: **fake** link verdicts, pink "MOCK" label |
| `.\scripts\amaan.ps1 up` / `down` / `status` / `logs` | full stack (what `start.bat` / `stop.bat` call) |

macOS / Linux / WSL: `./scripts/amaan.sh test | dev [--mock] | up | down | status | logs`.

GitHub runs the same tests on every pull request (`.github/workflows/ci.yml`).

## No Docker? Use GitHub Codespaces (in the browser)
Repo page → **Code** → **Codespaces** → **Create codespace on main** (4-core).
In its terminal: `./scripts/amaan.sh up`, then **Ports** tab → 8000 → 🌐.
Keep the port *Private*, use only the built-in examples (it runs on GitHub's
servers), and stop the codespace when done.

## Manual test checklist (before a demo or a big merge)
- [ ] Each **Try an example** button gives the expected result
- [ ] Paste text with Ctrl+V outside the text box, then drag a screenshot from File Explorer
- [ ] Camera: show `frontend/public/examples/03-open-wifi.png` on your phone
- [ ] Stop URL.vet (`docker compose -p urlvet stop backend`): link results say "Be careful" plus a warning, never "No warning signs"
- [ ] Links in results are defanged (`hxxps://…[.]…`) and not clickable

## Project layout
```
backend/amaan/       FastAPI app
  extract/           find links in text, decode QR codes, parse dropped HTML (all offline)
  clients/urlvet.py  talks to the URL.vet sandbox
  scoring/           local rules, Arabic/Arabizi scam phrases, final verdict + reasons
  data/brands.json   official domains (each entry must be checked by a teammate)
backend/tests/       pytest suite (incl. every built-in example)
backend/devtools/    fake URL.vet for --mock
frontend/src/        React UI (App.tsx, components/)
frontend/src/examples.json + public/examples/   built-in examples (regenerate: scripts/make_examples.py)
infra/urlvet/        config for URL.vet (its code is cloned, unmodified, into third_party/)
scripts/             amaan.ps1 / amaan.sh
```

## API (http://localhost:8000/api/docs)
| Endpoint | Body |
|---|---|
| `POST /analyze/text` | JSON `{text, html?, uri_list?}` |
| `POST /analyze/image` | multipart `file` (PNG/JPG/WebP), optional `source=camera` |
| `GET /health` | status, URL.vet reachable, QR decoders |

Every analysis returns the same Evidence object: `risk_level`, `explanation`,
`items[]` (each with `signals[]`, URL.vet result), message-level `signals[]`
and `warnings[]`. Every signal has a `label`: `automated_indicator`,
`community_report` or `verified`.

## Settings (environment variables)
`AMAAN_URLVET_BASE_URL` (default `http://localhost:8080`),
`AMAAN_MAX_URLS_PER_REQUEST` (10), `AMAAN_MAX_UPLOAD_BYTES` (10 MB),
`AMAAN_ALLOWED_HOSTS` (comma-separated; Codespaces sets it).

## Troubleshooting
| Problem | Fix |
|---|---|
| `start.bat` says Docker is not running | open Docker Desktop, wait for *Engine running* |
| Status says "Link checker starting…" | wait a minute; still there? `docker compose -p urlvet logs backend` |
| `429 Too Many Requests` while building | Docker Hub limit: wait 10 min or `docker login` |
| Port 8000 in use | `stop.bat`, close other servers |
| Camera doesn't start | use `http://localhost:8000` and allow the camera in the address bar |
