# WhatsApp integration: feasibility (Milestone 3)

Goal: let Amaan check suspicious WhatsApp messages (links, images with QR codes,
voice notes later) **for chats the user chooses**, without sending content to
any cloud.

## The four options

| | (a) Baileys | (b) whatsapp-web.js | (c) WhatsApp Business Cloud API | (d) "Export chat" import |
|---|---|---|---|---|
| What it is | Node library speaking WhatsApp Web's multi-device protocol directly (no browser) | Node library that drives the real WhatsApp Web inside headless Chrome (Puppeteer) | Meta's official API for **business** numbers, hosted by Meta | WhatsApp's own "Export chat" feature (.txt, or .zip with media) |
| Licence | MIT | Apache-2.0 | Proprietary service | n/a |
| Can read | Every message the linked account receives: text, links, images, voice notes, documents, in all chats and groups | Same as (a) | **Only messages people send to the business number.** It cannot read a user's personal chats | One chat at a time, up to the export limit (WhatsApp exports the most recent messages; fewer when media is included) |
| Real time | Yes | Yes | Yes (webhook) | No (manual) |
| Setup | `npm install`, scan a QR with the phone (Linked devices) | Same, plus a Chromium download | Meta Business account, a dedicated phone number, app review, a **public HTTPS webhook** | None: export on the phone, drop the file into Amaan |
| Windows | Yes (pure Node, or Docker) | Yes (heavier: Chromium, ~300 MB RAM) | n/a (cloud) | Yes |
| Privacy | Stays on the user's computer | Stays on the user's computer | Messages go through Meta's cloud **and** our public server; breaks our local-only rule | Stays on the user's computer |
| Reliability | Breaks when WhatsApp changes its protocol; community-maintained (v7 is still a release candidate) | Breaks when WhatsApp Web changes; slower startup | Stable, official | Stable; the text format varies by phone and language |
| Terms of Service / ban risk | **Unofficial client: against WhatsApp's Terms; numbers can be banned.** Risk is highest for sending or bulk activity; read-only use is lower but not zero | Same as (a) | None (official) | None (official feature) |

## Decision

1. **(d) Export import: built, on by default.** Zero risk, works for any
   chat, any phone, and is the safest thing to show in the demo.
2. **(a) Baileys: built as an opt-in "live" mode** (`start-whatsapp.bat`),
   for a **test number only**:
   - The user links it like WhatsApp Web and **ticks the chats** to watch. Other
     chats are never read (filtered inside the bridge, before anything leaves it).
   - Only **new incoming** messages are checked (not history, not the user's own).
   - It **never sends anything**: no replies, no read receipts, never shows "online".
   - It **never stores messages**: on disk only the login session and the list of
     selected chat ids. Flagged results are kept in RAM (last 50) for the screen.
   - Voice notes are detected but not analyzed until Milestone 2's pipeline exists.
   - Chosen over (b) because it needs no browser, is lighter, and has the same
     coverage and the same ban risk.
3. **(c) Cloud API: not used.** It cannot see personal chats. It only fits a
   future public "forward suspicious messages to the Amaan bot" service, which
   would need a server and a privacy review (see `DECISIONS.md`).

## How it's wired
```
Phone (test number) ──linked device──▶ whatsapp-bridge (Node, Baileys, Docker, no host port)
                                         │ only selected chats, new messages
                                         ▼ POST /whatsapp/ingest (shared secret)
                                       Amaan backend ──▶ same checks as the main screen ──▶ alerts in the UI
```

## Drag and drop from messaging apps on Windows (to test)
Amaan accepts **files** (images, `.txt`/`.zip` chat exports), **links**
(`text/uri-list`), **HTML** and **plain text**. What each app actually
provides when you drag out of it has to be checked by hand. Fill in this table
while testing (Windows 11, Chrome/Edge on `http://localhost:8000`):

| Drag this… | WhatsApp Desktop | WhatsApp Web | Telegram Desktop | Viber |
|---|---|---|---|---|
| A photo | | | | |
| A link in a message | | | | |
| Selected message text | | | | |
| A voice note | | | | |

Write what Amaan showed (e.g. "image analyzed", "link found", "nothing to
check"). If dragging doesn't work in an app, use copy (Ctrl+C) and paste
(Ctrl+V) instead: that path is supported for text, links and copied images.
