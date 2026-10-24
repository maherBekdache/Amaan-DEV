# Amaan: notes for AI agents

Start with `docs/HANDOFF.md` (setup, architecture, status, plan), then `docs/DECISIONS.md`.

Hard rules (from the project owner):
1. Never open, fetch or render an untrusted URL on the host or in the backend. Only URL.vet's (and Lookyloo's) sandbox does. QR contents are untrusted.
2. No user content leaves the machine; no new third-party cloud APIs without the owner's approval.
3. Every verdict shows its evidence; keep "automated indicator", "community report" and "verified" distinct.
4. Delete temporary uploads after analysis; no logs of message content.

Working style: brief, exact answers (Windows PowerShell 5.1 commands); ask before hard-to-undo
architecture choices; keep backend rules and `packages/core` in parity (tests enforce it); in `app/`
follow `app/AGENTS.md` (Expo SDK 57, `npx expo install`, `npm ci`).
