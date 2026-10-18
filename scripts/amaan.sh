#!/usr/bin/env bash
# Start/stop the Amaan stack from WSL, Linux or macOS.
#   ./scripts/amaan.sh up [--urlvet-ui] [--whatsapp] [--lookyloo] [--phone] | down | status | logs | setup | update-urlvet
#   ./scripts/amaan.sh dev [--mock]   hot-reload backend :8000 + frontend :5173
#                                     (--mock = FAKE URL.vet, development only)
#   ./scripts/amaan.sh test           backend tests + frontend type check
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URLVET_DIR="$ROOT/third_party/urlvet"
URLVET_REPO="https://github.com/urlvet/urlvet.git"
URLVET_REF="${URLVET_REF:-a6b54c29b73a053b916805173fba352e9be0204c}"  # pinned; bump deliberately
NETWORK="amaan-urlvet"
CMD="${1:-up}"
UI="${2:-}"
ARGS=" ${*:2} "
LOOKY_DIR="$ROOT/third_party/lookyloo"
LOOKY_REPO="https://github.com/Lookyloo/lookyloo.git"
LOOKY_REF="${LOOKYLOO_REF:-a37506c4ffc063464e016ecff8cfa79f7e65461d}"

looky_compose() {
  docker compose -p lookyloo -f "$LOOKY_DIR/docker-compose.yml" -f "$ROOT/infra/lookyloo/docker-compose.amaan.yml" "$@"
}

start_lookyloo() {
  if [ ! -d "$LOOKY_DIR" ]; then
    echo "==> Cloning Lookyloo (BSD-3, kept unmodified in third_party/)"
    git clone --quiet "$LOOKY_REPO" "$LOOKY_DIR"
    git -C "$LOOKY_DIR" -c advice.detachedHead=false checkout --quiet "$LOOKY_REF"
  fi
  cp "$ROOT/infra/lookyloo/generic.json" "$ROOT/infra/lookyloo/modules.json" "$LOOKY_DIR/config/"
  echo "==> Building and starting Lookyloo (first time: 10-20 minutes)"
  looky_compose up -d --build
}

urlvet_compose() {
  docker compose -p urlvet \
    -f "$URLVET_DIR/docker/prod/docker-compose.prod.yml" \
    -f "$ROOT/infra/urlvet/docker-compose.amaan.yml" "$@"
}

secret() { od -An -tx1 -N32 /dev/urandom | tr -d ' \n'; }

setup() {
  command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Docker is not running." >&2; exit 1; }
  if [ ! -d "$URLVET_DIR" ]; then
    echo "==> Cloning URL.vet (AGPL-3.0, kept unmodified in third_party/)"
    git clone --quiet "$URLVET_REPO" "$URLVET_DIR"
    git -C "$URLVET_DIR" -c advice.detachedHead=false checkout --quiet "$URLVET_REF"
  fi
  if [ ! -f "$URLVET_DIR/server/.env" ] || [ ! -f "$URLVET_DIR/docker/prod/.env" ]; then
    echo "==> Writing URL.vet configuration with fresh secrets"
    cache="$(secret)"
    sed -e "s/__CACHE_PASSWORD__/$cache/" -e "s/__JWT_SECRET__/$(secret)/" \
      "$ROOT/infra/urlvet/server.env.template" > "$URLVET_DIR/server/.env"
    printf 'CACHE_PASSWORD=%s\n' "$cache" > "$URLVET_DIR/docker/prod/.env"
  fi
  # Shared secret between Amaan and the WhatsApp bridge (read by docker compose from .env).
  grep -qs '^AMAAN_BRIDGE_TOKEN=' "$ROOT/.env" || printf 'AMAAN_BRIDGE_TOKEN=%s\n' "$(secret)" >> "$ROOT/.env"
  docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
}

dev_env() {
  if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
    echo "==> Creating backend/.venv (Python 3.11)"
    python3.11 -m venv "$ROOT/backend/.venv"
  fi
  "$ROOT/backend/.venv/bin/python" -m pip --version >/dev/null 2>&1 || "$ROOT/backend/.venv/bin/python" -m ensurepip --upgrade >/dev/null
  (cd "$ROOT/backend" && .venv/bin/python -m pip install --quiet -e ".[dev]")
  [ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm install --no-fund --no-audit)
}

case "$CMD" in
  dev)
    dev_env
    command -v docker >/dev/null && (cd "$ROOT" && docker compose stop amaan >/dev/null 2>&1 || true)
    pids=()
    trap 'kill "${pids[@]}" 2>/dev/null' EXIT INT TERM
    if [ "$UI" = "--mock" ]; then
      echo "!! MOCK URL.vet on :8080: verdicts are FAKE, never use it for the demo."
      (cd "$ROOT/backend" && .venv/bin/python -m uvicorn devtools.mock_urlvet:app --host 127.0.0.1 --port 8080) & pids+=($!)
    fi
    (cd "$ROOT/backend" && .venv/bin/python -m uvicorn amaan.main:app --reload --host 127.0.0.1 --port 8000) & pids+=($!)
    (cd "$ROOT/frontend" && npm run dev) & pids+=($!)
    echo "Open http://localhost:5173  (Ctrl+C stops everything)"
    wait
    ;;
  test)
    dev_env
    (cd "$ROOT/backend" && .venv/bin/python -m pytest -q)
    (cd "$ROOT/frontend" && npm run typecheck)
    echo "All checks passed."
    ;;
  setup) setup; echo "Setup done." ;;
  up)
    setup
    services=(backend chrome valkey)
    [[ "$ARGS" == *" --urlvet-ui "* ]] && services+=(web)
    echo "==> Building and starting URL.vet (${services[*]})"
    urlvet_compose up -d --build "${services[@]}"
    echo "==> Building and starting Amaan"
    [[ "$ARGS" == *" --lookyloo "* ]] && start_lookyloo
    profile=()
    [[ "$ARGS" == *" --whatsapp "* ]] && profile=(--profile whatsapp)
    files=(-f docker-compose.yml)
    if [[ "$ARGS" == *" --phone "* ]]; then
      ip="$( (hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null) | awk '{print $1}')"
      [ -n "$ip" ] || { echo "No network address found." >&2; exit 1; }
      touch "$ROOT/.env"
      grep -v '^AMAAN_PHONE_URL=' "$ROOT/.env" > "$ROOT/.env.tmp" || true
      mv "$ROOT/.env.tmp" "$ROOT/.env"
      echo "AMAAN_PHONE_URL=http://$ip:8001" >> "$ROOT/.env"
      grep -qs '^AMAAN_PHONE_TOKEN=.' "$ROOT/.env" || echo "AMAAN_PHONE_TOKEN=$(secret)" >> "$ROOT/.env"
      files+=(-f docker-compose.phone.yml)
      echo "==> Phone gateway on http://$ip:8001"
    fi
    (cd "$ROOT" && docker compose "${files[@]}" "${profile[@]}" up -d --build)
    for _ in $(seq 1 45); do
      if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
        echo; echo "Amaan is running:  http://localhost:8000"
        echo "URL.vet API:       http://localhost:8080/swagger/index.html"
        exit 0
      fi
      sleep 2
    done
    echo "Amaan did not answer yet. Check: ./scripts/amaan.sh logs" >&2
    ;;
  down)
    (cd "$ROOT" && docker compose --profile whatsapp down)
    [ -d "$URLVET_DIR" ] && urlvet_compose down
    [ -d "$LOOKY_DIR" ] && looky_compose down
    true
    ;;
  status)
    (cd "$ROOT" && docker compose ps)
    [ -d "$URLVET_DIR" ] && urlvet_compose ps
    curl -fsS http://localhost:8000/health || echo "Amaan is not answering on :8000" >&2
    ;;
  logs) (cd "$ROOT" && docker compose logs -f --tail 100) ;;
  update-urlvet)
    git -C "$URLVET_DIR" fetch --quiet origin
    git -C "$URLVET_DIR" -c advice.detachedHead=false checkout --quiet "$URLVET_REF"
    echo "URL.vet is at $URLVET_REF. Run './scripts/amaan.sh up' to rebuild."
    ;;
  *) echo "usage: $0 up [--urlvet-ui|--whatsapp] | down | status | logs | setup | update-urlvet | dev [--mock] | test" >&2; exit 2 ;;
esac
