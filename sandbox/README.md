# Sandbox services

Two small services that keep untrusted links away from the user's computer and
network. Design and rules: `docs/LINK_SECURITY.md` and `docs/DECISIONS.md` (D19).

| Service | What it does | Network |
|---|---|---|
| `egress/` | HTTP proxy: ports 80 and 443 to public internet addresses only; refuses private ranges, loopback, link-local (cloud metadata) and local IPv6. Resolves names itself and connects to the checked address. | `amaan-sandbox` (internal) + `amaan-egress` (out) |
| `expander/` | Expansion worker (layer L5): follows a link hop by hop (HTTP, meta refresh, script redirects read but never run), reads the last page's title, text and form fields, hashes downloads. No browser, no disk, no logs of links. | `amaan-sandbox` only; answers the backend over a Unix socket in the `expander-sock` volume |

URL.vet's headless Chrome is moved behind its own copy of the egress proxy by
`infra/urlvet/docker-compose.amaan.yml`.

Tests (no Docker or internet needed): `backend/.venv/bin/python -m pytest sandbox/tests`

Optional stronger isolation with gVisor: set `AMAAN_SANDBOX_RUNTIME=runsc` in `.env`
after installing gVisor (see `docs/LINK_SECURITY.md`).
