#!/bin/bash
#
# SessionStart hook for Claude Code on the web.
#
# Brings a fresh container to the point where every part of Estock can be run
# and tested straight away: Python deps, npm deps, the Flutter SDK, and a
# running PostgreSQL with migrations applied and demo data loaded.
#
# Everything here is idempotent — it is safe to run on every session start, and
# skips work that a cached container already has.
#
set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$PROJECT_DIR" || { echo "cannot enter $PROJECT_DIR" >&2; exit 0; }

# Only run in Claude Code on the web. Local machines use `make setup`.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

VENV="$PROJECT_DIR/.venv"
FLUTTER_HOME="${FLUTTER_HOME:-/opt/flutter}"
FLUTTER_VERSION="3.27.1"
PGDATA_DIR="/var/lib/estock/pgdata"
PGPORT=5432
PGBIN="/usr/lib/postgresql/16/bin"
DB_URL="postgresql+psycopg://estock:estock@localhost:${PGPORT}/estock"

log()  { printf '  %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
step() { printf '\n==> %s\n' "$*"; }

# --------------------------------------------------------------------------- #
# Python backend
# --------------------------------------------------------------------------- #
setup_python() {
  step "Backend (Python)"
  if [ ! -x "$VENV/bin/python" ]; then
    log "creating virtualenv"
    python3 -m venv "$VENV" || { warn "could not create virtualenv"; return 1; }
  fi
  # pip is quick when everything is already satisfied, and picks up changes to
  # requirements without needing to detect them.
  "$VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1
  if "$VENV/bin/pip" install --quiet -r backend/requirements-dev.txt; then
    log "dependencies installed"
  else
    warn "pip install failed — backend tests may not run"
    return 1
  fi
}

# --------------------------------------------------------------------------- #
# Web frontend
# --------------------------------------------------------------------------- #
setup_web() {
  step "Web (Next.js)"
  if [ -d web/node_modules ] && [ web/node_modules -nt web/package.json ]; then
    log "node_modules already current"
    return 0
  fi
  if (cd web && npm install --no-audit --no-fund >/dev/null 2>&1); then
    log "npm packages installed"
  else
    warn "npm install failed — the web app may not build"
    return 1
  fi
}

# --------------------------------------------------------------------------- #
# Flutter SDK
#
# ~700MB on a cold container, then cached. Best-effort: a failure here must not
# stop backend or web work.
# --------------------------------------------------------------------------- #
setup_flutter() {
  step "Mobile (Flutter)"
  if [ -x "$FLUTTER_HOME/bin/flutter" ]; then
    log "SDK already present at $FLUTTER_HOME"
  else
    log "downloading Flutter $FLUTTER_VERSION (one-off, ~700MB)"
    local archive="/tmp/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
    local url="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
    if ! curl -fsSL --retry 2 -o "$archive" "$url"; then
      warn "download failed — mobile work unavailable this session"
      return 1
    fi
    mkdir -p "$(dirname "$FLUTTER_HOME")"
    tar xf "$archive" -C "$(dirname "$FLUTTER_HOME")" || { warn "extract failed"; return 1; }
    rm -f "$archive"
    log "SDK installed"
  fi

  # Flutter refuses to run against a git checkout it does not own.
  git config --global --add safe.directory "$FLUTTER_HOME" 2>/dev/null || true
  export PATH="$FLUTTER_HOME/bin:$PATH"
  flutter config --enable-web --no-analytics >/dev/null 2>&1 || true
  if (cd mobile && flutter pub get >/dev/null 2>&1); then
    log "packages resolved"
  else
    warn "flutter pub get failed"
    return 1
  fi
}

# --------------------------------------------------------------------------- #
# PostgreSQL
#
# The production database, and what the full test suite runs against. A running
# server is never part of a cached container, so this always has to start it.
# --------------------------------------------------------------------------- #
setup_postgres() {
  step "PostgreSQL"
  if [ ! -x "$PGBIN/initdb" ]; then
    warn "PostgreSQL 16 is not installed — tests will fall back to SQLite"
    return 1
  fi

  if [ ! -s "$PGDATA_DIR/PG_VERSION" ]; then
    log "initialising cluster at $PGDATA_DIR"
    mkdir -p "$PGDATA_DIR" /var/run/postgresql
    chown -R postgres:postgres "$PGDATA_DIR" /var/run/postgresql
    su postgres -c "$PGBIN/initdb -D $PGDATA_DIR -U postgres --auth=trust" >/dev/null 2>&1 \
      || { warn "initdb failed"; return 1; }
  fi
  chown -R postgres:postgres "$PGDATA_DIR" /var/run/postgresql 2>/dev/null || true

  if su postgres -c "$PGBIN/pg_ctl -D $PGDATA_DIR status" >/dev/null 2>&1; then
    log "server already running"
  else
    log "starting server on port $PGPORT"
    su postgres -c "$PGBIN/pg_ctl -D $PGDATA_DIR -o '-p $PGPORT -c listen_addresses=localhost' -l /tmp/estock-pg.log -w start" \
      >/dev/null 2>&1 || { warn "could not start PostgreSQL (see /tmp/estock-pg.log)"; return 1; }
  fi

  # Role and databases match backend/.env.example and docker-compose.yml, so the
  # defaults work with no further configuration.
  su postgres -c "$PGBIN/psql -h localhost -p $PGPORT -U postgres -tAc \"SELECT 1 FROM pg_roles WHERE rolname='estock'\"" 2>/dev/null | grep -q 1 \
    || su postgres -c "$PGBIN/psql -h localhost -p $PGPORT -U postgres -c \"CREATE ROLE estock LOGIN PASSWORD 'estock' SUPERUSER\"" >/dev/null 2>&1
  for db in estock estock_test; do
    su postgres -c "$PGBIN/psql -h localhost -p $PGPORT -U postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='$db'\"" 2>/dev/null | grep -q 1 \
      || su postgres -c "$PGBIN/psql -h localhost -p $PGPORT -U postgres -c \"CREATE DATABASE $db OWNER estock\"" >/dev/null 2>&1
  done
  log "databases ready: estock, estock_test"
}

# --------------------------------------------------------------------------- #
# Backend environment file, migrations and demo data
# --------------------------------------------------------------------------- #
setup_backend_env() {
  step "Backend environment"
  if [ ! -f backend/.env ]; then
    local secret
    secret="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))' 2>/dev/null || echo "dev-only-$RANDOM")"
    sed -e "s|^DATABASE_URL=.*|DATABASE_URL=$DB_URL|" \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=$secret|" \
        backend/.env.example > backend/.env
    log "wrote backend/.env with a generated SECRET_KEY"
  else
    log "backend/.env already present"
  fi
}

setup_database_schema() {
  step "Migrations and demo data"
  if ! (cd backend && DATABASE_URL="$DB_URL" "$VENV/bin/alembic" upgrade head >/dev/null 2>&1); then
    warn "migrations failed — check the database is running"
    return 1
  fi
  log "migrations applied"

  # Seeding refuses to duplicate, so this is safe on every start.
  if (cd backend && DATABASE_URL="$DB_URL" "$VENV/bin/python" -m app.seed >/dev/null 2>&1); then
    log "demo data ready (owner@merkato-demo.et / demo-password-123)"
  else
    warn "seeding skipped or failed"
  fi
}

# --------------------------------------------------------------------------- #
# Persist environment for the session
# --------------------------------------------------------------------------- #
write_env() {
  [ -n "${CLAUDE_ENV_FILE:-}" ] || return 0
  {
    echo "export PATH=\"$FLUTTER_HOME/bin:$VENV/bin:\$PATH\""
    echo "export DATABASE_URL=\"$DB_URL\""
    echo "export TEST_DATABASE_URL=\"postgresql+psycopg://estock:estock@localhost:${PGPORT}/estock_test\""
    echo "export NEXT_PUBLIC_API_BASE_URL=\"http://localhost:8000/api/v1\""
    echo "export PLAYWRIGHT_BROWSERS_PATH=\"/opt/pw-browsers\""
  } >> "$CLAUDE_ENV_FILE"
  log "environment exported for this session"
}

# --------------------------------------------------------------------------- #

echo "Setting up Estock…"
failed=()

setup_python        || failed+=("python")
setup_web           || failed+=("web")
setup_flutter       || failed+=("flutter")
setup_postgres      || failed+=("postgres")
setup_backend_env   || failed+=("env")
setup_database_schema || failed+=("schema")
write_env

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "Estock is ready. Run 'make help' to see what you can do."
else
  echo "Estock is ready, except: ${failed[*]}"
  echo "Everything else still works; see the warnings above."
fi

# Never block the session on a partial setup — the warnings say what is missing.
exit 0
