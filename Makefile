# Estock — common tasks.
#
# In Claude Code on the web, .claude/hooks/session-start.sh has already run
# setup for you; go straight to `make api`, `make test` and so on.
# On your own machine, start with `make setup` (or just `docker compose up`).

SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

DB_URL      ?= postgresql+psycopg://estock:estock@localhost:5432/estock
TEST_DB_URL ?= postgresql+psycopg://estock:estock@localhost:5432/estock_test
API_URL     ?= http://localhost:8000/api/v1

export DATABASE_URL := $(DB_URL)

.DEFAULT_GOAL := help
.PHONY: help demo setup setup-backend setup-web setup-mobile \
        api web mobile mobile-web worker \
        migrate seed reset-db \
        test test-backend test-backend-pg test-mobile \
        lint lint-backend lint-web lint-mobile fix \
        build-web build-apk docker clean

help: ## Show this help
	@echo "Estock — make targets"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Demo sign-in after 'make seed':"
	@echo "  owner@merkato-demo.et / demo-password-123"

# --------------------------------------------------------------------------- #
# Manual testing
# --------------------------------------------------------------------------- #

demo: ## Everything running for manual testing — no database to install
	@./scripts/demo.sh

# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #

setup: setup-backend setup-web setup-mobile ## Install everything (needs Python 3.11+, Node 22+, Flutter)
	@echo
	@echo "Setup complete. Start PostgreSQL, then: make migrate seed api"

setup-backend: ## Create the virtualenv and install Python dependencies
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r backend/requirements-dev.txt
	@test -f backend/.env || { \
	  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$$($(PY) -c 'import secrets; print(secrets.token_urlsafe(48))')|" \
	      backend/.env.example > backend/.env; \
	  echo "wrote backend/.env with a generated SECRET_KEY"; }
	@echo "backend ready"

setup-web: ## Install web dependencies
	@cd web && npm install --no-audit --no-fund
	@echo "web ready"

setup-mobile: ## Resolve Flutter packages
	@cd mobile && flutter pub get
	@echo "mobile ready"

# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #

api: ## Run the API with reload on http://localhost:8000
	@cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run the reminder/alert/trial worker once
	@cd backend && ../$(VENV)/bin/python -m app.workers.scheduler

web: ## Run the web app on http://localhost:3000
	@# Next already binds 0.0.0.0, but say so explicitly: it matches
	@# docker-compose and does not depend on that default staying put.
	@cd web && NEXT_PUBLIC_API_BASE_URL=$(API_URL) npm run dev -- -H 0.0.0.0

mobile: ## Run the Flutter app (needs a device or emulator)
	@cd mobile && flutter run --dart-define=API_BASE_URL=$(API_URL)

mobile-web: ## Serve the Flutter app at http://localhost:8090 — no Android tooling needed
	@# Built rather than `flutter run -d web-server`, which ignores
	@# --no-web-resources-cdn and then renders nothing without CDN access.
	@cd mobile && flutter build web --release --no-web-resources-cdn \
	  --dart-define=API_BASE_URL=$(API_URL)
	@echo
	@echo "Open http://localhost:8090 and switch your browser to a phone size."
	@echo "Press Ctrl-C to stop."
	@cd mobile/build/web && python3 -m http.server 8090

docker: ## Run the whole stack in Docker, with demo data
	@SEED_ON_START=true docker compose up --build

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

migrate: ## Apply database migrations
	@cd backend && ../$(VENV)/bin/alembic upgrade head

seed: ## Load the demo business (safe to re-run)
	@cd backend && ../$(VENV)/bin/python -m app.seed

reset-db: ## Drop everything and rebuild from migrations, then seed
	@cd backend && ../$(VENV)/bin/alembic downgrade base && ../$(VENV)/bin/alembic upgrade head
	@$(MAKE) --no-print-directory seed

# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

test: test-backend test-mobile ## Run the backend and mobile suites

test-backend: ## Backend tests on SQLite (fast)
	@cd backend && DATABASE_URL="sqlite://" ../$(VENV)/bin/pytest

test-backend-pg: ## Backend tests on PostgreSQL (also covers row locking)
	@cd backend && TEST_DATABASE_URL="$(TEST_DB_URL)" DATABASE_URL="$(TEST_DB_URL)" ../$(VENV)/bin/pytest

test-mobile: ## Flutter tests
	@cd mobile && flutter test

# --------------------------------------------------------------------------- #
# Linting
# --------------------------------------------------------------------------- #

lint: lint-backend lint-web lint-mobile ## Lint everything

lint-backend: ## Lint the backend
	@cd backend && ../$(VENV)/bin/ruff check .

lint-web: ## Typecheck and lint the web app
	@cd web && npx tsc --noEmit && npm run lint

lint-mobile: ## Analyze the Flutter app
	@cd mobile && flutter analyze

fix: ## Apply the fixes the backend linter can make itself
	@cd backend && ../$(VENV)/bin/ruff check --fix .

# --------------------------------------------------------------------------- #
# Builds
# --------------------------------------------------------------------------- #

build-web: ## Production build of the web app
	@cd web && NEXT_PUBLIC_API_BASE_URL=$(API_URL) npm run build

build-apk: ## Release APK for Android
	@cd mobile && flutter build apk --release --dart-define=API_BASE_URL=$(API_URL)

clean: ## Remove build output and caches
	@rm -rf web/.next mobile/build backend/.pytest_cache backend/.ruff_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "cleaned"
