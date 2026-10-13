# Contributing

## Setup (once)
1. Ask the owner to add you: repo **Settings → Collaborators**. Accept the e-mail invite.
2. Install what the [README](README.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) list, then
   `git clone https://github.com/maherBekdache/Amaan-DEV.git`.

## Every change
```powershell
git switch main; git pull
git switch -c feat/my-change            # one branch per task
# ...edit...
.\scripts\amaan.ps1 test                # must pass
git add -A; git commit -m "Add Whish lookalike rule"
git push -u origin feat/my-change
```
Open a **Pull Request** on GitHub → a teammate reviews → **Squash and merge**.
CI runs the tests automatically.

## Rules (reviewers block PRs that break them)
1. Our code never opens, fetches or displays an analyzed link (no `fetch(url)`, no `<a href>`, no `<img src>` of user links). Only URL.vet's sandbox does.
2. No user content leaves the computer. A new online service needs a team decision in `docs/DECISIONS.md`.
3. Every warning is a `Signal` with a clear title, detail and label (`automated_indicator`, `community_report` or `verified`).
4. Never log message text, links or images.
5. Don't edit URL.vet's code; only configure it in `infra/urlvet/`.
6. New rule = new test. Demo-worthy? Add it to `frontend/src/examples.json`.
7. No real people's messages or live scam links in code, tests or issues. Use `example.com` links.
