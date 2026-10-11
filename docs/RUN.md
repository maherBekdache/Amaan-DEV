# How to run Amaan: exact commands

Two supported ways:

| | Where it runs | Use it for | Needs |
|---|---|---|---|
| **A. Windows laptop** | your PC (Docker Desktop) | **the demo video**, real use | Windows 10/11, 16 GB RAM recommended |
| **B. GitHub Codespaces** | a cloud VM, opened in your browser | trying it anywhere, teammates without Docker, reviewing PRs | a GitHub account with access to the repo |

Both run the real URL.vet sandbox. Codespaces runs on GitHub's servers, so
paste **only the demo samples** there, never real people's messages.

---

## A. Windows laptop

### A1. One-time installs
Open **PowerShell as Administrator** (Start → type *PowerShell* → *Run as administrator*):

```powershell
wsl --install
winget install -e --id Git.Git
winget install -e --id Docker.DockerDesktop
```
Reboot. Start **Docker Desktop** from the Start menu, accept the terms, and
wait until the bottom-left says **Engine running**. Leave it open.

### A2. Get the code (once)
Open a **normal** PowerShell (not admin):

```powershell
cd $HOME\Documents
git clone https://github.com/maherBekdache/Amaan-DEV.git
cd Amaan-DEV
```
If the repo is private, a GitHub sign-in window pops up; sign in.

### A3. Start (every time)
```powershell
cd $HOME\Documents\Amaan-DEV
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\amaan.ps1 up
```
- First run: 5-15 minutes (downloads and builds URL.vet + Amaan). Later runs: ~30 s.
- The browser opens **http://localhost:8000**. Wait until the top-right pill is
  **green: "Link sandbox (URL.vet) online"** (up to a minute after start).

### A4. Run the demo
```powershell
explorer demo\qr          # opens the QR sample folder: drag files onto the page
notepad demo\README.md    # sample messages: copy one, click the page, Ctrl+V
```
Follow the shot list in `docs/DEMO.md`. Camera: click **Scan QR with
camera**, allow the webcam, and show a QR from `demo\qr` on your phone screen.

### A5. Stop / update
```powershell
.\scripts\amaan.ps1 down          # stop everything
git pull                          # get teammates' changes
.\scripts\amaan.ps1 up            # rebuilds what changed
.\scripts\amaan.ps1 status        # what is running
```

### A6. For coding (optional)
```powershell
winget install -e --id Python.Python.3.11
winget install -e --id OpenJS.NodeJS.LTS
# close and reopen PowerShell, then in the repo folder:
.\scripts\amaan.ps1 test          # all automated checks
.\scripts\amaan.ps1 dev           # hot reload on http://localhost:5173 (keeps URL.vet from 'up')
```

---

## B. On the web: GitHub Codespaces

### B1. Create the codespace (once)
1. Go to https://github.com/maherBekdache/Amaan-DEV
2. Green **Code** button → **Codespaces** tab → **Create codespace on main**
   (if asked for a machine type, pick **4-core**).
3. Wait for setup to finish (~3-5 min; it installs Python, Node and the dependencies
   from `.devcontainer/devcontainer.json`).

### B2. Start (in the codespace's terminal at the bottom)
```bash
./scripts/amaan.sh up
```
First run ~10 minutes. Then open the **Ports** tab → row **8000 (Amaan (full
stack))** → click the 🌐 globe icon. The page opens at
`https://<your-codespace>-8000.app.github.dev`. Leave the port's visibility on
**Private**: only people signed in to GitHub with access to the codespace
can open it.

The webcam works there too (the page is HTTPS). Your browser streams your
own camera; only the captured still frame is sent to the codespace.

### B3. Faster, without URL.vet (link verdicts are fake)
```bash
./scripts/amaan.sh dev --mock
```
Then Ports → **5173** → globe. A pink **MOCK** banner shows on every result;
good for UI work, not for the demo.

### B4. Stop (saves your free hours)
```bash
./scripts/amaan.sh down
```
Then on https://github.com/codespaces → **⋯** next to the codespace → **Stop codespace**.
Free personal accounts include a limited number of core-hours per month, and a
4-core machine uses 4 per hour. Codespaces also stop automatically after 30
minutes idle.

---

## C. WSL, macOS or Linux
Same as B2-B4 on your own machine, with Docker installed:
```bash
git clone https://github.com/maherBekdache/Amaan-DEV.git && cd Amaan-DEV
./scripts/amaan.sh up      # http://localhost:8000
```

---

## Why there is no public website (yet)
A public URL would mean users' messages and images are uploaded to our server.
That breaks our rule that no user content leaves the machine, and it opens our
URL.vet sandbox (20 checks per minute) to anyone on the internet. For the
jury, record the video (A) or share your screen from a codespace (B). If a
hosted version is ever needed, it needs a team decision first (login, HTTPS,
rate limiting, privacy notice) recorded in `docs/DECISIONS.md`.

## Something went wrong?
| Symptom | Fix |
|---|---|
| `amaan.ps1 cannot be loaded` | run the `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` line first (same window) |
| "Docker Desktop is not running" | start Docker Desktop, wait for *Engine running* |
| Pill amber "URL.vet offline" | wait 1 min; then `docker compose -p urlvet ps` and `docker compose -p urlvet logs backend` |
| `429 Too Many Requests` during build | Docker Hub limit: wait 10 min or `docker login` |
| Port 8000 already in use | `.\scripts\amaan.ps1 down`, close other servers, retry |
| Camera black / denied | use `http://localhost:8000` (not the PC's IP); allow the camera icon in the address bar |
| Codespace page says "Invalid host" | open it from the Ports tab (globe icon), not by typing the URL |
