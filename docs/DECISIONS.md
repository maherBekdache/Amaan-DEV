# Architecture & privacy decisions

Short log of choices that are hard to undo, with who approved them.

## D1. URL.vet runs as a separate, unmodified service
*Approved by the team, Oct 2026 ("do what is more feasible").*

- `scripts/amaan.ps1` / `amaan.sh` clones URL.vet at a **pinned commit** into
  `third_party/urlvet/`, which is git-ignored, so its AGPL-3.0 code never
  enters our repository.
- We do not edit its code. We only add configuration:
  - `server/.env` and `docker/prod/.env`, generated from
    `infra/urlvet/server.env.template` with fresh random secrets;
  - a Compose overlay (`infra/urlvet/docker-compose.amaan.yml`) that binds
    its ports to `127.0.0.1` and joins its backend to the `amaan-urlvet`
    Docker network.
- Amaan talks to it over HTTP only (`GET /api/v1/analyze?url=`).
- We run URL.vet as its own Compose project (`-p urlvet`) rather than with
  Compose `include:`, so our compose file does not depend on its internal
  file layout. `docker compose up` on our side works without it (local rules
  only, clearly marked "incomplete").
- URL.vet allows 20 requests/minute per client and this is hard-coded. We cap
  links per request at 10 and show "rate limited" instead of a verdict.

## D2. Links leave the machine through URL.vet (exception to hard rule 2)
*Approved by the team, Oct 2026.*

Checking a link means something must contact it. URL.vet's container:
- fetches the destination page (HTTP/TLS/DNS) and follows redirects;
- looks up domain registration data (RDAP/WHOIS);
- asks the PhishTank API about the link **only until** PhishTank's
  downloadable list has loaded (normally a few seconds after start), then
  checks it locally.

What never leaves the machine: message text, images, QR images, audio,
history. Only the **link itself** goes to those services, and only after the
user asks for it to be checked.

Kept **off**: Google Safe Browsing / Web Risk, URLhaus and OpenPhish
(opt-in in URL.vet; enabling any of them needs team approval). URL.vet log
files are disabled (`LOG_DIR` empty).

## D3. Short links are never expanded by our code
*Approved by the team, Oct 2026 ("most secure and practical").*

Expanding a short link means requesting it, which is exactly the
"open untrusted URL" that hard rule 1 forbids. Our backend only recognizes
known shorteners (a local list) and flags them. URL.vet follows the chain
inside its container and we show the full chain ("Where it really goes")
from its report. Our HTTP client has `follow_redirects=False` and ignores
system proxy settings.

## D4. One process serves API + UI; camera works on localhost
- The backend serves the built frontend at `http://localhost:8000`, so the
  browser talks to a single origin: no CORS, a strict Content-Security-Policy
  (`connect-src 'self'`, no external images, scripts or frames), and camera
  access works because `localhost` counts as a secure context.
- The Vite dev server (`:5173`) proxies to the backend and is the only extra
  CORS origin.
- Electron later: the build uses relative asset paths and `VITE_API_BASE`.

## D5. History is stored only in the browser, without content
*Approved by the team, Oct 2026.*

`localStorage` holds: time, input type, verdict, item count and up to 5
**defanged host names**. No message text, full URLs, images or QR payloads.
"Clear history" wipes it.

## D6. Uploads never touch disk (or are deleted right away)
- Images are decoded from memory (Pillow -> numpy -> OpenCV/zbar).
- If the multipart parser spools a large upload to a temp file, the endpoint
  closes it in a `finally:` block, which deletes it. In Docker that temp space
  is a `tmpfs` (RAM) and the container filesystem is read-only.
- Bodies larger than the limit are rejected from the `Content-Length` header
  before being read.

## D7. Logging
We log events and counts only. `httpx` request logging is silenced because it
would print the `?url=` being checked. A test asserts that links and message
text never appear in logs.

## D8. Evidence labels
- `automated_indicator`: an algorithm decided (URL.vet checks, Amaan rules,
  keyword cues).
- `community_report`: people reported it (threat lists such as PhishTank,
  via URL.vet).
- `verified`: matched a curated, trusted source. Today that is only
  `backend/amaan/data/brands.json` (official domains). **Each entry must be
  checked by a team member**: a wrong entry would mark a fake site as
  verified.

## D9. Local API hardening
- Ports bound to `127.0.0.1` only (Amaan and URL.vet).
- Host-header allowlist blocks DNS-rebinding attacks from websites in the
  user's browser.
- Container: non-root user, read-only root filesystem, all capabilities
  dropped, `no-new-privileges`.

## Open items for the team
- [ ] Verify every official domain in `backend/amaan/data/brands.json`.
- [ ] Decide on Lookyloo "deep inspect" (see `LINK_TOOLS_COMPARISON.md`).
- [ ] Decide whether a PhishIntention spike fits the ML part of the report.
