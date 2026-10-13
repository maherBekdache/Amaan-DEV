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
  scan the QR with the phone (Linked devices), and tick the chats to watch. New suspicious messages appear automatically.
  Details and risks: [docs/FEASIBILITY.md](docs/FEASIBILITY.md).

Demo video plan: [docs/DEMO.md](docs/DEMO.md).

## Work on it
- How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md)
- Developer guide (tests, dev mode, Codespaces, API, project layout): [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Design and privacy decisions: [docs/DECISIONS.md](docs/DECISIONS.md)

| Milestone | | |
|---|---|---|
| 1 | Links + QR codes (text, drop, upload, webcam) | ✅ |
| 2 | Lebanese voice-note transcription | next |
| 3 | WhatsApp: chat-export import + live watching of selected chats | ✅ |
