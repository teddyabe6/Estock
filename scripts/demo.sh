#!/usr/bin/env bash
#
# One command to get Estock running for manual testing.
#
#   ./scripts/demo.sh
#
# Uses SQLite, so there is no database to install. Starts the API and the web
# app, loads the demo business, and stops both cleanly on Ctrl-C.
#
# For the real thing — PostgreSQL, the background worker, the mobile app — see
# docs/local-setup.md.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

VENV="$ROOT/.venv"
DB_FILE="$ROOT/backend/var/demo.db"
LOG_DIR="$ROOT/backend/var"
API_LOG="$LOG_DIR/api.log"
WEB_LOG="$LOG_DIR/web.log"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
API_URL="http://localhost:${API_PORT}/api/v1"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }
fail()  { printf '\n  Error: %s\n\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------- #
# Prerequisites
# --------------------------------------------------------------------------- #
command -v python3 >/dev/null || fail "Python 3.11+ is required. See docs/local-setup.md"
command -v node    >/dev/null || fail "Node.js 20+ is required. See docs/local-setup.md"
command -v npm     >/dev/null || fail "npm is required (it ships with Node.js). See docs/local-setup.md"

# On WSL, Windows' own PATH is appended to yours. If Windows' Node is found
# first, `npm run` shells out to CMD.EXE, which cannot use a \\wsl.localhost
# path or run this project's Linux binaries. Catch that here rather than
# letting it fail later with a confusing CMD.EXE message.
for tool in node npm; do
  tool_path="$(command -v "$tool" 2>/dev/null || true)"
  case "$tool_path" in
    /mnt/*)
      printf '\n  Error: `%s` here is Windows'"'"' %s, at\n    %s\n' "$tool" "$tool" "$tool_path" >&2
      cat >&2 <<'HOWTO'

  It runs through CMD.EXE, which cannot use this project's files.
  Node needs to be installed inside WSL itself.

  The quickest way, without sudo:

    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    exec $SHELL -l
    nvm install 22

  Or system-wide:

    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs

  Then check it took effect — this must NOT start with /mnt/:

    which node

  Then run this again. Anything Windows' npm already wrote into
  web/node_modules is replaced for you:

    ./scripts/demo.sh

HOWTO
      exit 1
      ;;
  esac
done

python3 - <<'PY' || fail "Python 3.11 or newer is required."
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
  else
    # Fall back to a connection attempt when lsof is unavailable.
    (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
  fi
}
port_busy "$API_PORT" && fail "Port $API_PORT is in use. Set API_PORT=8001 and try again."
port_busy "$WEB_PORT" && fail "Port $WEB_PORT is in use. Set WEB_PORT=3001 and try again."

# --------------------------------------------------------------------------- #
# Setup (skipped when already done)
# --------------------------------------------------------------------------- #
bold "Setting up"

if [ ! -x "$VENV/bin/python" ]; then
  info "creating the Python environment"
  python3 -m venv "$VENV" || fail "could not create a virtualenv"
fi
info "installing backend dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1
"$VENV/bin/pip" install --quiet -r backend/requirements-dev.txt \
  || fail "pip install failed"

# An existing node_modules is not enough: one installed by Windows' npm holds
# .cmd shims rather than runnable Linux binaries, so check for the real thing.
if [ ! -x web/node_modules/.bin/next ]; then
  if [ -d web/node_modules ]; then
    info "web dependencies are unusable here, reinstalling"
    rm -rf web/node_modules
  else
    info "installing web dependencies (first run takes a minute)"
  fi
  (cd web && npm install --no-audit --no-fund >/dev/null 2>&1) \
    || fail "npm install failed"
  [ -x web/node_modules/.bin/next ] \
    || fail "npm install finished but left no runnable 'next'. See docs/local-setup.md"
fi

mkdir -p "$LOG_DIR"
export DATABASE_URL="sqlite:///$DB_FILE"
export SECRET_KEY="${SECRET_KEY:-demo-only-not-for-deployment}"
export PUBLIC_BASE_URL="http://localhost:${WEB_PORT}"
# 8090 is where `make mobile-web` serves the Flutter app for browser testing.
CORS_LIST="http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT},http://localhost:8090,http://127.0.0.1:8090"
# Also allow this machine's own addresses, so the app works when opened from a
# WSL VM address or from a phone on the same network.
for ip in $(hostname -I 2>/dev/null); do
  CORS_LIST="${CORS_LIST},http://${ip}:${WEB_PORT},http://${ip}:8090"
done
export CORS_ORIGINS="$CORS_LIST"

info "preparing the database"
(cd backend && "$VENV/bin/alembic" upgrade head >/dev/null 2>&1) \
  || fail "migrations failed"
(cd backend && "$VENV/bin/python" -m app.seed >/dev/null 2>&1) || true

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
API_PID=""
WEB_PID=""
cleanup() {
  printf '\n  Stopping…\n'
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null
  wait 2>/dev/null
  printf '  Stopped. Your data is kept in backend/var/demo.db\n'
}
trap cleanup INT TERM EXIT

bold ""
bold "Starting"
(cd backend && "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$API_PORT" --log-level warning) > "$API_LOG" 2>&1 &
API_PID=$!

# Wait for the API before starting the web app, so the first page load works.
for _ in $(seq 1 40); do
  if curl -fsS -m 2 "http://localhost:${API_PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
if ! curl -fsS -m 2 "http://localhost:${API_PORT}/health" >/dev/null 2>&1; then
  printf '\n  The API did not start. Last lines of %s:\n\n' "$API_LOG" >&2
  tail -n 25 "$API_LOG" >&2
  fail "see above"
fi
info "API ready on http://localhost:${API_PORT}"

(cd web && NEXT_PUBLIC_API_BASE_URL="$API_URL" npm run dev -- -p "$WEB_PORT" -H 0.0.0.0) > "$WEB_LOG" 2>&1 &
WEB_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS -m 2 "http://localhost:${WEB_PORT}" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
if ! curl -fsS -m 2 "http://localhost:${WEB_PORT}" >/dev/null 2>&1; then
  printf '\n  The web app did not start. Last lines of %s:\n\n' "$WEB_LOG" >&2
  tail -n 25 "$WEB_LOG" >&2
  fail "see above"
fi
info "Web ready on http://localhost:${WEB_PORT}"

# On WSL, Windows forwards localhost into the VM — but not always for every
# port (a port inside a Hyper-V reserved range fails this way, and looks exactly
# like the server being down). Print the VM address too, which always works.
WSL_HINT=""
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  WSL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [ -n "$WSL_IP" ]; then
    WSL_HINT="
  If localhost does not load in your Windows browser, use these instead:
    Web app     http://${WSL_IP}:${WEB_PORT}
    API docs    http://${WSL_IP}:${API_PORT}/docs
"
  fi
fi

cat <<BANNER

$(bold "Estock is running")

  Web app       http://localhost:${WEB_PORT}
  API docs      http://localhost:${API_PORT}/docs
  Online shop   http://localhost:${WEB_PORT}/shop/merkato-wholesale
${WSL_HINT}
  Sign in as                 to see
  ----------------------------------------------------------------
  owner@merkato-demo.et      everything, including cost and profit
  manager@merkato-demo.et    operations for the Bole branch only
  cashier@merkato-demo.et    sales only — no cost, no profit
  store@merkato-demo.et      stock only — cannot sell

  Every password is: demo-password-123

  Cannot reach it in your browser? Run ./scripts/doctor.sh
  Logs: backend/var/api.log and backend/var/web.log
  Press Ctrl-C to stop.

BANNER

# Watch both servers. If one dies — Next running out of memory or file watchers
# is the usual cause on WSL — say so and show why, instead of looking healthy.
while true; do
  sleep 5
  if ! kill -0 "$API_PID" 2>/dev/null; then
    printf '\n  The API stopped. Last lines of %s:\n\n' "$API_LOG" >&2
    tail -n 25 "$API_LOG" >&2
    exit 1
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    printf '\n  The web app stopped. Last lines of %s:\n\n' "$WEB_LOG" >&2
    tail -n 25 "$WEB_LOG" >&2
    exit 1
  fi
done
