# Testing Amaan locally

Three levels. Run 1 before every push and 2 before every merge to `main`.
Do 3 on each Windows laptop before the demo.

## 1. Automated checks (30 seconds)

```powershell
.\scripts\amaan.ps1 test          # Windows
./scripts/amaan.sh test           # WSL / Linux / macOS
```

This runs:
- **pytest** (`backend/tests`): URL extraction (Arabic, Arabizi, punycode,
  hidden characters), QR decoding on generated images, URL.vet client failures
  (down, timeout, 429, bad JSON), scoring rules, every API endpoint, privacy
  (nothing logged), and every demo sample.
- **TypeScript type check** of the frontend.

GitHub runs the same checks on every pull request (`.github/workflows/ci.yml`).

## 2. Run it and click around

Pick the mode that fits your laptop:

| Mode | Command | Needs | Link verdicts |
|---|---|---|---|
| **Full** (use for the demo) | `.\scripts\amaan.ps1 up` → http://localhost:8000 | Docker Desktop | real (URL.vet) |
| **Dev, real URL.vet** | `up` once, then `.\scripts\amaan.ps1 dev` → http://localhost:5173 | Docker + Python 3.11 + Node 20 | real; hot reload on save |
| **Dev, mock** | `.\scripts\amaan.ps1 dev -Mock` → http://localhost:5173 | Python 3.11 + Node 20 | **fake**: pink "MOCK" banner |

The mock exists so a teammate whose laptop can't run Docker can still work on
the UI or rules. Never record the demo with it: every result says "MOCK".

## 3. Manual checklist (Windows, real URL.vet)

Copy this into the PR or an issue and tick it. Use the files in `demo/`.

**Inputs**
- [ ] Drag `demo/qr/01-official-omt.png` from File Explorer → Low, *Verified*
- [ ] Drag `02-at-sign-trick.png` → High, "hides its real destination with '@'"
- [ ] Drag `07-three-codes.png` → 3 items
- [ ] *Upload image…* button with `08-photo-of-poster.jpg` → QR found
- [ ] Copy a PNG (open it, Ctrl+C) and press Ctrl+V on the page → analyzed
- [ ] Paste each message from `demo/README.md` with Ctrl+V (focus **not** in the text box) → expected level
- [ ] Type a message in the box, Ctrl+Enter → analyzed
- [ ] Select a link on a web page and drag it into the drop zone → "dropped link"
- [ ] Drag a link from WhatsApp Desktop / Web and from Telegram → note what arrives (feeds Milestone 3)
- [ ] *Scan QR with camera*: show `03-open-wifi.png` on your phone → Medium, Wi-Fi
- [ ] Camera: deny permission → clear message, no crash
- [ ] Drop a .gif, a .pdf, a .mp3 → friendly "not supported" message

**Failure handling**
- [ ] `docker compose -p urlvet stop backend`, then paste a link → **Medium**, "URL.vet is not running", *Incomplete check*; pill turns amber
- [ ] Start it again: `docker compose -p urlvet start backend` → pill green within 30 s
- [ ] Drop a >10 MB image → "too large"
- [ ] Paste 15 links at once → only 10 checked, warning shown

**Privacy / safety**
- [ ] Links in results are defanged (`hxxps://…[.]…`) and not clickable
- [ ] DevTools → Network: the page only talks to `localhost`
- [ ] DevTools → Application → Local Storage: history has hosts only, no message text
- [ ] *Clear history* empties it
- [ ] `docker compose logs amaan`: no links or message text
- [ ] From another device on the same Wi-Fi, `http://<laptop-ip>:8000` does **not** load (localhost only)

## Reporting a bug
Open a GitHub issue with the *Bug report* template. **Never paste a real
person's message or a live scam link into an issue:** defang it
(`hxxps://evil[.]com`) and remove names and numbers.
