#!/usr/bin/env bash
# Start/stop the Amaan stack from WSL, Linux or macOS.
#   ./scripts/amaan.sh up [--urlvet-ui] | down | status | logs | setup | update-urlvet
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
    [ "$UI" = "--urlvet-ui" ] && services+=(web)
    echo "==> Building and starting URL.vet (${services[*]})"
    urlvet_compose up -d --build "${services[@]}"
    echo "==> Building and starting Amaan"
    (cd "$ROOT" && docker compose up -d --build)
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
    (cd "$ROOT" && docker compose down)
    [ -d "$URLVET_DIR" ] && urlvet_compose down
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
  *) echo "usage: $0 up [--urlvet-ui] | down | status | logs | setup | update-urlvet | dev [--mock] | test" >&2; exit 2 ;;
esac
