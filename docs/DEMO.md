# Demo video plan (target: 3-4 minutes)

## The day before
- [ ] `git pull` on the recording laptop, then `.\scripts\amaan.ps1 up`. The first
      build takes a while; don't do it live.
- [ ] Top-right pill is **green** ("Link sandbox (URL.vet) online"), **not** pink/MOCK.
- [ ] Run each sample once so URL.vet's cache is warm (repeat scans are instant).
- [ ] Pick today's PhishTank link for the "community report" shot (see `demo/README.md`).
- [ ] Clear history, close other tabs, browser zoom 110-125%, hide bookmarks bar.
- [ ] Notifications off (Windows Focus Assist), phone on silent.
- [ ] Recorder: Xbox Game Bar (Win+G) or OBS, 1080p, record the browser window only.

## Shot list

| # | Time | What you do | What you say (gist) |
|---|---|---|---|
| 1 | 0:00 | Show a WhatsApp-style scam message (`arabic-prize`) | "Lebanese users get messages like this every day: prizes, OMT, codes." |
| 2 | 0:20 | Copy it, press Ctrl+V on Amaan | "Just paste. Nothing is opened: the link is checked in an isolated sandbox." |
| 3 | 0:35 | Point at the High verdict, open the item | "Every verdict shows its evidence: the domain uses OMT's name but isn't OMT; the message asks for a code and promises a prize." Point at the labels: *automated indicator* vs *verified*. |
| 4 | 1:05 | Paste `arabizi-code` | "It reads Arabizi too." |
| 5 | 1:20 | Drag `02-at-sign-trick.png` | "QR codes on posters and stickers: this one looks like omt.com.lb but opens something else." |
| 6 | 1:40 | Drag `01-official-omt.png` | "The real OMT site is recognized as verified, so we're not just flagging everything." |
| 7 | 1:55 | Camera button, hold phone showing `03-open-wifi.png` | "Or scan with the webcam. This QR joins an open Wi-Fi network, a classic fake hotspot." |
| 8 | 2:20 | Paste today's PhishTank link | "Links reported by others show as a *community report*." |
| 9 | 2:40 | Paste a short link (any bit.ly you created to aub.edu.lb) | "Short links are followed inside the sandbox; we show where it really goes." |
| 10 | 3:00 | Stop URL.vet (`docker compose -p urlvet stop backend`), paste a link | "If a check can't run, we say so. 'Not checked' never looks like 'safe'." |
| 11 | 3:20 | History panel, then architecture slide | "History stays on this computer, without message text. Next: voice notes and WhatsApp." |

Make the shot-9 short link yourself (bit.ly → `https://www.aub.edu.lb`) so you
know where it goes.

## If something goes wrong while recording
- Pill amber: wait 30 s; URL.vet loads its lists at start.
- Verdict takes >15 s: URL.vet's own time limit; cut it in editing.
- "Rate limit reached": URL.vet allows 20 checks a minute; wait a minute.
