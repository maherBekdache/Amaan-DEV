# Link / QR checking engines: URL.vet vs. Lookyloo vs. PhishIntention

Researched October 2026 from each project's current repository (licence file,
README, Docker files, config samples and API code).

## TL;DR

| | **URL.vet** | **Lookyloo** | **PhishIntention** |
|---|---|---|---|
| What it is | URL risk scorer: 20+ parallel checks, gives a verdict | Web-capture and forensics tool: maps every domain/redirect a page loads | Deep-learning phishing detector: "does this page look like brand X *and* ask for credentials?" |
| Output | `Safe / Suspicious / Risky`, 0-100 score, plain-English reasons (JSON) | Capture tree, redirects, screenshot, HTML, cookies, hostnames, IPs (JSON); **no verdict** | `Phish / Benign` + impersonated brand + confidence |
| Licence | AGPL-3.0 (or commercial) | BSD-3-Clause | Code: CC0 1.0. **Model weights:** downloaded from Google Drive with no licence stated (see below) |
| Can we use it? | Yes, as a separate, unmodified service (that is what we do) | Yes, permissive; could even be modified/embedded | Code yes; ask authors about weights before any public release |
| HTTP API | Yes: `GET /api/v1/analyze?url=` | Yes: `/submit`, then poll `/json/<uuid>/status`, read `/json/<uuid>/redirects`, screenshot, etc. (`pylookyloo` client) | **No.** CLI over folders (`info.txt` + `shot.png` [+ `html.txt`]); we would write a small wrapper |
| Speed per URL | 1-15 s | ~10-60 s per capture | ~1-3 s on GPU, several seconds on CPU, per screenshot (plus page capture) |
| Footprint | 4 small containers (Go API, headless Chrome, Valkey, optional UI) | 3 containers (Python app with Playwright browsers, 2 Valkey); a few GB of disk over time | PyTorch + Detectron2 + Chrome; multi-GB image; GPU recommended |
| Windows | Docker Desktop (WSL2); `make` optional | Docker Desktop (WSL2) via its `docker-compose.yml` | Docker or native via Pixi scripts (`setup.bat`); Detectron2 on Windows is the fragile part |
| Lebanese brands | Brand-mismatch check only knows popular sites | n/a (no verdict) | Ships 277 global brands; Lebanese banks/OMT/Whish need their logos + domains added to its reference list |
| Ease for our team | Easy: one script, one JSON call | Medium: async submit/poll, config to harden | Hard: ML stack, no API, weights download, slow on CPU |

**Recommendation**

1. **Milestone 1: URL.vet stays the verdict engine.** It is the only one of
   the three that returns a score with reasons, which our UI needs.
2. **Lookyloo: optional "Deep inspect" button** (Milestone 4 candidate).
   It is strong *evidence* for the explainability rule: the full redirect
   tree and a screenshot taken in a container, without the user ever opening
   the link. It needs hardening (below) and gives no verdict by itself.
3. **PhishIntention: later research module** for visual brand-impersonation
   detection (e.g. "this page looks like BLOM Bank but is not blombank.com").
   It works best fed with a screenshot that URL.vet or Lookyloo already took.
   Run it in **static mode only** (steps 1-3 and 5) so it never visits a page
   itself. Good fit for the ML part of the project; too heavy for the November
   demo unless the GPU machine runs it.

The backend's link-checking client is behind one interface
(`amaan/clients/urlvet.py` -> per-item `UrlVetResult`), so adding a
Lookyloo or PhishIntention client later only means adding another evidence
source to the same item.

## Security each one gives the user

### URL.vet
- Follows shorteners and redirects server-side and scans the **final**
  destination. Our backend never resolves a short link itself.
- Checks domain age (RDAP/WHOIS), TLS, typosquatting, punycode/homoglyphs,
  login/payment forms, brand-name mismatch, hidden iframes, script
  redirects, and threat lists (PhishTank by default; URLhaus, OpenPhish and
  Google Safe Browsing are opt-in).
- Headless Chrome runs in its own container (`chromedp/headless-shell`);
  the host browser never loads the page.
- Privacy: the backend contacts the destination site and RDAP/WHOIS
  servers. PhishTank's API is asked only until its local list has loaded.
  Logs contain no scanned links. We leave every opt-in feed **off** (see
  `DECISIONS.md`).
- Limit: hard-coded 20 requests/minute per client IP. Our client caps URLs
  per request and reports "rate limited" instead of a fake verdict.

### Lookyloo
- Captures with Playwright **inside its container**. It records every
  hostname, redirect, script and iframe the page pulls in, and the cookies it
  sets. That is the best "show me what this link really does" evidence.
- `only_global_lookups: true` (default) refuses private/internal IPs. That
  matters for QR codes pointing at `192.168.x.x` router pages.
- Options for a safer capture: `java_script_enabled=0` and
  `allow_tracking=0` per submission.
- **Risks we must configure away before using it:**
  - It **keeps captures** (screenshots, HTML, cookies) on disk, archived
    after 180 days. That conflicts with "no content logs". We would set
    `default_public: false` and delete each capture after reading it
    (`/admin/<uuid>/remove`, needs an admin user), or wipe the volume on
    a schedule.
  - Some modules call third parties: SaneJS (on by default; sends JS hashes
    to CIRCL), CIRCL passive DNS, and Cloudflare IP-list fetches. VirusTotal,
    urlscan.io and PhishTank are off unless keys are set. Disable all of them
    in `config/modules.json` so only the capture itself leaves the machine.
  - The web UI on :5100 must be bound to 127.0.0.1.

### PhishIntention
- Detects **brand + credential-taking intention** from the page's look: a
  logo of a known brand on a login page whose domain is not that brand's.
  That catches fresh phishing sites that threat lists and domain-age checks
  miss.
- Published at USENIX Security 2022 with a peer-reviewed evaluation, which is
  useful to cite in our report.
- **Risks/limits:**
  - Step 4 (CRP locator) drives a real Chrome via Selenium and clicks
    through the site. If run natively it would visit untrusted pages from
    the host, which breaks hard rule 1. It must run in a container, or we
    skip step 4 and feed it screenshots only.
  - Brand coverage is only as good as its logo list; Lebanese brands must be
    added by us.
  - Weights come from Google Drive via `gdown`. The repo's CC0 licence
    covers the code, but no licence is stated for the weights. Fine for an
    academic prototype; ask the authors before any public release.
  - Python/ML stack (PyTorch, Detectron2) is heavy; CPU-only inference is
    slow.

## Licence compatibility with our code
- **URL.vet (AGPL-3.0):** we never copy, link or modify its code. We clone it
  into the git-ignored `third_party/` and talk to it over HTTP only. Our own
  code keeps whatever licence the team picks. If we ever *modify* URL.vet
  and expose it over a network, we must publish those modifications.
- **Lookyloo (BSD-3):** permissive. Keep its copyright notice if we
  redistribute it.
- **PhishIntention (CC0):** public domain dedication for the code. Detectron2
  is Apache-2.0. Model weights' terms are unclear (above).
