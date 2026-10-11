# Working on Amaan together

## One-time setup (each teammate)
1. Get added as a collaborator on the GitHub repo (owner: Settings → Collaborators → Add people),
   and accept the e-mail invite.
2. Install: Git, Docker Desktop (WSL2), Python 3.11, Node 20+, VS Code (recommended).
3. Clone and run once:
   ```powershell
   git clone https://github.com/maherBekdache/Amaan-DEV.git
   cd Amaan-DEV
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\scripts\amaan.ps1 up      # full stack, http://localhost:8000
   .\scripts\amaan.ps1 test    # all automated checks
   ```
4. Tell Git who you are: `git config --global user.name "Your Name"` and `user.email`.

## Who owns what (suggested split, change freely)
| Area | Folder | Milestone |
|---|---|---|
| Links, QR, scoring rules, UI | `backend/amaan/{extract,scoring,clients}`, `frontend/` | 1 |
| Voice: audio pipeline, Whisper, anti-spoofing, scam intent | `backend/amaan/voice/` (to come) | 2 |
| WhatsApp bridge + chat-export import | `whatsapp-bridge/`, `backend/amaan/importers/` (to come) | 3 |

Owning an area means you review PRs touching it, not that others can't edit it.

## Daily workflow
```powershell
git switch main
git pull
git switch -c feat/short-description     # one branch per task
# ...edit, then:
.\scripts\amaan.ps1 test
git add -A
git commit -m "Add Whish lookalike rule"  # small commits, imperative mood
git push -u origin feat/short-description
```
Then open a **pull request** on GitHub into `main`:
- fill in the template (what, why, how you tested);
- CI must be green (tests + type check run automatically);
- one teammate reviews and approves, then **Squash and merge**;
- delete the branch after merging.

Branch names: `feat/…`, `fix/…`, `docs/…`, `test/…`. Keep PRs small (under
~400 changed lines) so reviews take minutes, not days.

If `main` moved while you worked: `git switch main && git pull && git switch -
&& git merge main`, then fix conflicts, test, and push.

## Rules that protect the project
These come from our project constraints; reviewers block PRs that break them.
1. **Never fetch, open or render an untrusted URL** in our code (no `requests.get(url)`,
   no `<a href>` to analyzed links, no `<img src>` from user content, no link previews).
   Only URL.vet's containers touch untrusted destinations. QR content is untrusted.
2. **No user content leaves the machine.** No new cloud API without team approval
   (write it in `docs/DECISIONS.md`).
3. **Every verdict shows its evidence**: new checks return a `Signal` with a clear title,
   detail, severity and the right label (`automated_indicator` / `community_report` / `verified`).
4. **No logging of message content, links or images.** Uploads are deleted after analysis.
5. **Don't modify URL.vet** (AGPL). Configure it only through `infra/urlvet/`.
6. **Every new rule gets a test**, and if it is demo-worthy, a sample in `demo/samples.json`.

## Test data etiquette
- Use `example.com` subdomains for fake scam links in tests and samples.
- Never commit real people's messages, phone numbers or chats. Anonymize (Ali → A., +961 70 xxx).
- Never commit live phishing links. Defang them in issues: `hxxps://evil[.]com`.
- Secrets (`.env`, API keys) are git-ignored; never commit them.

## Asking Claude (or any AI) for help
Fine to use. You are responsible for the diff: read it, run `test`, and say in the
PR what the AI did.
