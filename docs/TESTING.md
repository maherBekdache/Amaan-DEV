# Testing guide

Work through the parts you need. Tick each box; anything that fails → open a GitHub
issue with the step number, what you saw, and a screenshot (never paste real
private messages).

**Safety while testing:** never click a link from a result, use a **test WhatsApp
number** for live watching, and only use the fake scams in `samples/` and the
built-in examples (or links copied as text from PhishTank).

## 0. Install once (Windows)
| What | Needed for |
|---|---|
| [Git](https://git-scm.com/download/win), [Docker Desktop](https://www.docker.com/products/docker-desktop/) | everything |
| [Node.js 22 LTS](https://nodejs.org/) | phone / desktop app, `amaan.ps1 test` |
| [Python 3.11](https://www.python.org/downloads/release/python-3119/) | `amaan.ps1 test` only |
| [Ollama](https://ollama.com/download), then `ollama pull qwen2.5:3b` | AI second opinion |
| **Expo Go** on the phone (App Store / Play Store) | phone app |
| Free API keys in `.env` (copy `.env.example`) | Safe Browsing, VirusTotal, urlscan.io, URLhaus rows |

```powershell
git clone https://github.com/maherBekdache/Amaan-DEV.git
cd Amaan-DEV
git pull          # every time before testing
```
Then double-click **`start-everything.bat`** (Docker Desktop must say *Engine running*).
First time 15-30 min. When it finishes, open **http://localhost:8000**.

## 1. Automated tests (2 min)
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\amaan.ps1 test
```
- [ ] 1.1 Ends with **All checks passed** (backend, web app, phone rules).
- [ ] 1.2 Phone app: `cd app; npm install; npx tsc --noEmit` shows no errors.

## 2. Web app on the computer (http://localhost:8000, **Check** tab)
- [ ] 2.1 Status (top right) turns **Ready** within ~1 min.
- [ ] 2.2 Every **Try an example** button gives the expected result:

  | Dangerous | Be careful | No warning signs |
  |---|---|---|
  | Arabic prize scam, Arabizi code scam, Bank threat, Parcel fee, Hidden characters, Lookalike site, Fake OMT QR, Crypto QR | Free Wi-Fi QR, Paid SMS QR, Fake file link | Real OMT QR (*Verified* reason), Phone call QR, Normal chat |
- [ ] 2.3 Each result shows **Why?** reasons with a label (*Automated check*, *Reported by others* or *Verified*).
- [ ] 2.4 Drag a screenshot from `frontend\public\examples\` onto the page → QR result.
- [ ] 2.5 **Scan a QR with the camera**, show `03-open-wifi.png` on your phone → open Wi-Fi warning.
- [ ] 2.6 Links in results look like `hxxps://site[.]com` and can't be clicked.

## 3. Security sources (multi-source verdict)
- [ ] 3.1 Paste `omt-lb-gift.com/claim` → **Show technical details** → table **Security sources: N of M flagged it**, one row per source (URL.vet, OpenPhish/URLhaus lists, Safe Browsing, VirusTotal, urlscan.io).
- [ ] 3.2 Sources without a key say **Not set up** (not an error). Add the key to `.env`, run `stop.bat` + `start-everything.bat` → the row now has a result.
- [ ] 3.3 Paste a link copied (as text) from today's PhishTank / OpenPhish list → at least one row **Flagged**, reason labelled *Reported by others*.

## 4. AI second opinion + Lookyloo
- [ ] 4.1 With Ollama running, a result shows an **AI second opinion** card (automatic, or **Ask the AI**). It never replaces the verdict above it.
- [ ] 4.2 Lookyloo is up: http://127.0.0.1:5100 opens its page (only on this computer).
- [ ] 4.3 For a link result the AI card says **Page opened in Lookyloo's sandbox.** (can take up to a minute). If Lookyloo is off, the card still works and says why the page wasn't opened.
- [ ] 4.4 Quit Ollama (tray icon) → the card says **Local AI is off…**; the normal verdict still works.

## 5. WhatsApp on the computer (**WhatsApp** tab)
**Chat export (no login):**
- [ ] 5.1 **Upload exported chat** → `samples\WhatsApp Chat with Test Group.zip` → 3 dangerous messages + the fake OMT QR in the photo; Mom and Ali not listed.
- [ ] 5.2 Export a real chat from your phone (chat → name → **Export chat**) and upload it → no crash, sensible results.

**Live watching** (test number only):
- [ ] 5.3 **Link WhatsApp** → scan the QR with the phone (WhatsApp → Settings → **Linked devices** → **Link a device**) → state **Watching**.
- [ ] 5.4 Default mode is **Unknown numbers (recommended)**: saved contacts are not watched.
- [ ] 5.5 From a number **not saved** in the test phone, send the Arabizi scam text from `samples\…txt` → it appears under **Suspicious messages** within seconds.
- [ ] 5.6 Same text from a **saved contact** → nothing appears (unless you tick that chat).
- [ ] 5.7 Call the test number from an unknown number → a **call** alert (foreign number = *Be careful*).
- [ ] 5.8 `stop.bat` then `start-whatsapp.bat` → reconnects by itself, chat list still there.
- [ ] 5.9 **Unlink** removes "Amaan" from the phone's Linked devices.

## 6. Phone app (iPhone / Android)
Setup: on the computer, `cd app`, `npm install`, `npx expo start`. Scan the terminal QR
(iPhone: Camera app; Android: Expo Go). Phone and computer on the **same Wi-Fi**
(not AUB's: use a hotspot). Then **Connect to computer** → scan the code on
http://localhost:8000 → **📱 Phone app**.
- [ ] 6.1 Top right shows **● 192.168.x.x:8001** after pairing.
- [ ] 6.2 **Check** tab: paste the Arabic prize scam → **Dangerous** with reasons; the link says *Checked online*.
- [ ] 6.3 **📷 Scan QR** at a QR on the computer screen (the examples) → same results as the web app; the QR's link is never opened.
- [ ] 6.4 **🖼️ Screenshot**: pick a screenshot of a QR code → result.
- [ ] 6.5 Turn the computer's Amaan off (`stop.bat`) → checks still work, links say *Not checked online* and are never "No warning signs".
- [ ] 6.6 **WhatsApp** tab → **Pick exported chat** → choose the sample `.zip` (AirDrop / Files) or a real export saved to Files → same findings as 5.1, photo QR included.
- [ ] 6.7 With 5.3 running: **Live alerts from your computer** shows the alerts from 5.5 / 5.7 (refreshes every 15 s while the screen is open).
- [ ] 6.8 **Disconnect** (tap the address) → app works offline; scanning the pairing QR in the normal scanner is refused with a hint.

## 7. Desktop / browser app
- [ ] 7.1 In the `npx expo start` terminal press **w** → the same app opens in the browser.
- [ ] 7.2 On http://localhost:8000 → 📱 Phone app → **Copy pairing link**, paste it in the app's **Connect to computer** → connected.
- [ ] 7.3 Checks from section 6 (paste, screenshot, WhatsApp export) work in the browser.
- [ ] 7.4 Chrome/Edge → address bar **Install** icon → Amaan opens as its own window.

## 8. Privacy and safety checks
- [ ] 8.1 *Recent checks* (web app) show verdicts only, never the message text.
- [ ] 8.2 `docker compose logs amaan` contains no message text or links.
- [ ] 8.3 From the phone's browser, http://<computer-ip>:8001/health → **Invalid host header** (only the paired app's link checks get in).
- [ ] 8.4 Restart Amaan → WhatsApp alerts are gone (kept in memory only).

## Reporting a problem
Issue title: `[TESTING 6.6] iPhone: export zip not accepted`. Include: device and OS,
what you did, what you expected, what you saw, screenshot, and for start-up problems
the last 30 lines of the PowerShell window. More fixes: [DEVELOPMENT.md → Troubleshooting](DEVELOPMENT.md#troubleshooting).
