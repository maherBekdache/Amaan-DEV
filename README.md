# Amaan (أمان)

Check if a message, link or QR code is a scam, in Arabic, Arabizi or English.
Paste it, drop it, upload a screenshot, or show a QR to your webcam. Amaan
answers **Dangerous / Be careful / No warning signs** and explains **why**.

- Links are never opened on your computer: they are tested inside an isolated
  sandbox ([URL.vet](https://github.com/urlvet/urlvet), running in Docker).
- Messages, images and history stay on your computer.

AUB final-year project prototype.

## Run it (Windows)

**Install once:** [Git](https://git-scm.com/download/win) and
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (it sets up WSL2 for you; reboot when asked).

```powershell
git clone https://github.com/maherBekdache/Amaan-DEV.git
```

**Start:** open Docker Desktop and wait for *Engine running*, then double-click
**`start.bat`** in the `Amaan-DEV` folder. The first start takes 5-15 minutes,
later ones about 30 seconds. Then open **http://localhost:8000**.

**Stop:** double-click **`stop.bat`**.

macOS / Linux / WSL: `./scripts/amaan.sh up` and `./scripts/amaan.sh down`.

## Try it
Click any **Try an example** button on the page: scam messages, a fake and a
real OMT QR code, a free Wi-Fi QR, several QR codes in one image. Or paste
your own text, drop a screenshot, or click **Scan a QR with the camera**.

**WhatsApp tab:**
- **Check a whole chat:** export it from WhatsApp (chat → ⋮ → More → Export chat) and upload the file. No login needed.
- **Watch chats live** (optional, test number only): start with **`start-whatsapp.bat`**, click *Link WhatsApp*,
  scan the QR with the phone (Linked devices). By default Amaan watches **numbers that aren't in your contacts** and
  unknown callers; family and friends stay private unless you tick them. Suspicious messages and calls appear automatically.
  Details and risks: [docs/FEASIBILITY.md](docs/FEASIBILITY.md).

**Extra checks (optional):**
- **Security sources** (Google Safe Browsing, VirusTotal, urlscan.io, URLhaus): copy
  `.env.example` to `.env` and paste your free keys, then restart. Without keys those rows show "Not set up".
- **AI second opinion** (runs on your computer): install [Ollama](https://ollama.com/download), then in
  PowerShell run `ollama pull qwen2.5:3b` once. Amaan finds it automatically.
- **Lookyloo** (opens links in a sandbox for the AI): start with **`start-everything.bat`** instead
  (first time 10-20 minutes).

## Phone app (iOS, Android, web, desktop)
One app in `app/` (React Native + Expo). It checks messages and QR codes **on the phone**;
only links are sent to your computer's sandbox and security sources.

**Install once:** [Node.js 22 LTS](https://nodejs.org/) on the computer, **Expo Go** on the phone (App Store / Play Store).

1. Double-click **`start-everything.bat`** (allow it through the Windows firewall if asked).
2. In PowerShell:
   ```powershell
   cd Amaan-DEV\app
   npm install
   npx expo start
   ```
3. Scan the QR code in the terminal: Android with **Expo Go**, iPhone with the **Camera** app.
   Phone and computer must be on the **same Wi-Fi** (on AUB Wi-Fi, use your phone's hotspot instead).
4. In the app tap **Connect to computer**, then scan the code in **http://localhost:8000 → 📱 Phone app**.

**WhatsApp tab in the app:** check an exported chat on the phone, and see the live alerts of
the computer's WhatsApp watcher. Test files: [samples/](samples/).

**Web / desktop:** press `w` in the same terminal (opens the app in the browser; Chrome/Edge can
*Install* it as a desktop app). Pair it with **Copy pairing link** on the 📱 Phone app tab.
Without pairing, the app still works, but links are marked *not checked online*.

**Testing everything step by step:** [docs/TESTING.md](docs/TESTING.md).

Demo video plan: [docs/DEMO.md](docs/DEMO.md) · Future directions: [docs/FUTURE.md](docs/FUTURE.md).

## Work on it
- How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md)
- Developer guide (tests, dev mode, Codespaces, API, project layout): [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Design and privacy decisions: [docs/DECISIONS.md](docs/DECISIONS.md)

| Milestone | | |
|---|---|---|
| 1 | Links + QR codes (text, drop, upload, webcam) | ✅ |
| 2 | Lebanese voice-note transcription | next |
| 3 | WhatsApp: chat-export import + live watching of selected chats | ✅ |
| + | Phone app (iOS / Android / web / desktop), multi-source link check, AI second opinion | ✅ |
