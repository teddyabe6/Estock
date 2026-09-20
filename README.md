# Estock

Shop management, inventory, sales, credit and an online catalogue for Ethiopian
small and medium businesses.

One catalogue and one stock ledger serve both the counter and the online shop.
A business owns its branches, staff, catalogue and transactions, and no
business can see another's data.

## What works today

| Area | Status |
| --- | --- |
| Registration, business profile, first branch, staff invitations | Done |
| Roles and granular permissions, branch assignment, tenant isolation | Done |
| Products, categories, variants, cost and price fields, opening stock | Done |
| Spreadsheet import: upload → map → preview → confirm | Done |
| Stock ledger, receiving, transfers, adjustments, counts, low-stock alerts | Done |
| Point of sale: search, barcode, discounts, split payment, credit | Done |
| Customers and suppliers with transaction history | Done |
| Credit receivables and payables, partial payments, due dates, reminders | Done |
| Online catalogue, enquiries, proformas with a secure share link | Done |
| Dashboards and reports for sales, profit, stock, branches and credit | Done |
| Trial and subscription state, platform-admin surface, audit trail | Done |
| Amharic-ready interface, ETB, Ethiopian phone formats | Text renders correctly everywhere; UI strings not yet translated |
| Flutter mobile app — sales, stock, credit, shop | Done |
| Offline sale capture and sync, with a stated conflict policy | Done (mobile) |
| Payment gateways, AI assistant, purchase orders | Later releases, by design |

## Quick start

```bash
make docker      # the whole stack in Docker, with demo data
```

Or without Docker:

```bash
make setup       # virtualenv, npm packages, Flutter packages, backend/.env
make migrate seed
make api         # then `make web` and `make mobile` in other terminals
```

Once it is up:

- Web app: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

`make help` lists every target. In **Claude Code on the web** none of this is
needed: a SessionStart hook does the setup for you — see
[Working in Claude Code on the web](#working-in-claude-code-on-the-web).

`make docker` seeds the demo business for you; plain `docker compose up`
starts empty.

That creates **Merkato Wholesale** with two branches, four staff accounts, ten
products, stock, sales, a supplier payable, an overdue receivable, a published
storefront and a proforma.

| Account | Email | Password |
| --- | --- | --- |
| Owner | `owner@merkato-demo.et` | `demo-password-123` |
| Manager | `manager@merkato-demo.et` | `demo-password-123` |
| Salesperson | `cashier@merkato-demo.et` | `demo-password-123` |
| Stock user | `store@merkato-demo.et` | `demo-password-123` |
| Platform admin | `admin@estock.et` | `admin-password-123` |

Sign in as the salesperson to see permissions at work: no cost, no profit, no
business-wide reports.

The demo catalogue includes Amharic product names, so you can see Ethiopic text
rendering in both clients.

## Working in Claude Code on the web

`.claude/hooks/session-start.sh` runs on every session start and leaves the
container ready to work: Python and npm dependencies, the Flutter SDK, a running
PostgreSQL with migrations applied and demo data loaded, and `backend/.env` with
a generated secret. It is idempotent, so a cached container finishes in a few
seconds and only a cold one pays for the Flutter download.

It also exports `DATABASE_URL`, `TEST_DATABASE_URL` and `PATH` for the session,
so `make test-backend-pg` and `flutter test` work immediately with no setup.

The hook does nothing on a local machine — `make setup` covers that. To check it
by hand:

```bash
CLAUDE_CODE_REMOTE=true ./.claude/hooks/session-start.sh
```

## Common tasks

| Command | What it does |
| --- | --- |
| `make setup` | Install everything on your own machine |
| `make api` / `make web` / `make mobile` | Run each part |
| `make worker` | Run reminders, low-stock alerts and trial expiry once |
| `make migrate` / `make seed` / `make reset-db` | Database |
| `make test` | Backend (SQLite) and mobile suites |
| `make test-backend-pg` | Backend against PostgreSQL, covering row locking |
| `make lint` | ruff, tsc + eslint, and flutter analyze |
| `make build-web` / `make build-apk` | Production builds |

## Tests

```bash
make test              # 219 backend tests on SQLite + 31 mobile tests
make test-backend-pg   # the same backend suite against PostgreSQL
```

SQLite keeps the loop short. PostgreSQL is not optional, though: it enforces
`VARCHAR` limits and has real row locking, and running the suite against it
caught a bug SQLite accepted silently — see
[docs/architecture.md](docs/architecture.md).

The suite covers what the PRD asks for: pricing and landed cost, credit
balances and due-date rules, permission boundaries, proof that one business
cannot read or modify another's data, duplicate submissions and retries,
timezone and Amharic handling, and the end-to-end onboarding, import, sale,
credit-payment, reminder and proforma workflows.

CI runs lint, applies migrations, checks the migrations still match the models,
and runs the tests against both databases.

## Repository layout

```
backend/            FastAPI service — the only place business rules live
  app/core/         Config, database, security, permissions, tenancy, audit
  app/models/       SQLAlchemy models (42 tables)
  app/services/     Domain logic: pricing, inventory, sales, credit, …
  app/api/v1/       HTTP routes and response shaping
  app/workers/      Scheduled reminders, alerts and trial expiry
  alembic/          Migrations
  tests/            219 tests
web/                Next.js app (owner, manager, cashier and storefront)
mobile/             Flutter app for the shop floor, works offline
  lib/core/offline/ Outbox, sync service and catalogue cache
  test/             31 tests
docs/               Architecture, decisions and roadmap
```

## How to read the code

Five decisions explain most of the design. Each is described in
[docs/architecture.md](docs/architecture.md):

1. **Tenant isolation** goes through `tenant_query` and `get_tenant_object`, so
   a forgotten filter is a visible omission rather than a silent leak.
2. **Authorisation checks permissions, never roles**, so custom role bundles can
   be added later without touching call sites.
3. **Stock is an append-only ledger** with a cached balance that a
   reconciliation endpoint proves still agrees with it.
4. **One payment ledger** backs sales, purchases and credit settlement, so no
   two tables track the same money.
5. **Credit status is always derived** from balance, due date and cancellation,
   so a transaction with money outstanding can never read as paid.

A sixth applies to the mobile app: **a sale captured offline is provisional
until the server accepts it**, and the interface says so. See
[mobile/README.md](mobile/README.md) for the conflict policy.

## Documentation

- [docs/architecture.md](docs/architecture.md) — how the pieces fit, and why
- [docs/decisions.md](docs/decisions.md) — the PRD's open decisions, what was
  chosen for now, and what still needs a business answer
- [docs/roadmap.md](docs/roadmap.md) — what is deliberately not built yet
- [docs/prd.md](docs/prd.md) — the source PRD, converted to Markdown

## Before production

The PRD is explicit that some questions need a business or legal answer rather
than a technical one. The ones that block a production launch are listed at the
top of [docs/decisions.md](docs/decisions.md) — tax and invoice requirements,
data residency, and the email and Telegram delivery approach among them.
