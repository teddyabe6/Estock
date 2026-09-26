# Estock

Shop management, inventory, sales, credit and an online catalogue for Ethiopian
small and medium businesses.

One catalogue and one stock ledger serve both the counter and the online shop.
A business owns its branches, staff, catalogue and transactions, and no
business can see another's data.

## What works today

| Area | Status |
| --- | --- |
| Registration, business profile, first branch, staff invitations | Done — the inviter gets the accept link to pass on; an existing account keeps its password |
| Roles and granular permissions, branch assignment, tenant isolation | Done |
| Products, categories, variants, cost and price fields, opening stock | Done, with editing and a price suggestion from the pricing rule |
| Spreadsheet import: upload → map → preview → confirm | Done, in the API and the web app |
| Stock ledger, receiving, transfers, adjustments, counts, low-stock alerts | Done; a transfer received short posts the shortfall as a loss |
| Point of sale: search, barcode, discounts, split payment, credit, receipts | Done |
| Customers and suppliers with transaction history | Done |
| Credit receivables and payables, partial payments, due dates, reminders, follow-up | Done |
| Online catalogue, enquiries, proformas with a secure share link | Done, managed from the web app |
| Dashboards and reports for sales, profit, stock, branches and credit | Done, with CSV export |
| Trial and subscription state, platform-admin surface, audit trail | Done; support access is read-only and audited |
| Sign-in rate limiting, password reset | Done |
| Amharic-ready interface, ETB, Ethiopian phone formats, business-local dates | Text renders correctly everywhere; days follow the business's timezone; UI strings not yet translated |
| Flutter mobile app — sales (cash or credit), stock, credit, shop | Done |
| Offline sale capture and sync, with a stated conflict policy | Done (mobile) |
| Payment gateways, AI assistant, purchase orders | Later releases, by design |

## Quick start

To try it by hand, with nothing to install but Python 3.11+ and Node 20+:

```bash
./scripts/demo.sh
```

That installs what it needs, loads a demo business and starts the API and the
web app. It uses SQLite, so there is no database to set up.
[docs/local-setup.md](docs/local-setup.md) covers what to click through, the
mobile app, and what to do when something does not start.

For the fuller setup — PostgreSQL, the background worker, hot reload:

```bash
make docker      # everything in Docker, with demo data
# or
make setup && make migrate seed && make api
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
business-wide reports, no Shop or Reports tab.

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
make test              # 257 backend tests on SQLite + 35 mobile tests
make test-backend-pg   # the same backend suite against PostgreSQL, plus a real concurrency test
```

SQLite keeps the loop short. PostgreSQL is not optional, though: it enforces
`VARCHAR` limits and has real row locking, and running the suite against it
caught a bug SQLite accepted silently — see
[docs/architecture.md](docs/architecture.md). One test only runs there: two
transactions asking for a sale number at the same moment, proving the second
waits for the first.

The suite covers what the PRD asks for: pricing and landed cost, credit
balances and due-date rules, permission boundaries, proof that one business
cannot read or modify another's data, duplicate submissions and retries,
timezone and Amharic handling, rate limiting, account recovery, and the
end-to-end onboarding, import, sale, credit-payment, reminder and proforma
workflows.

CI runs lint, applies migrations, checks the migrations still match the models,
runs the tests against both databases, typechecks and builds the web app, and
analyzes, tests and builds the mobile app.

## Repository layout

```
backend/            FastAPI service — the only place business rules live
  app/core/         Config, database, security, permissions, tenancy, audit,
                    business-local clock, rate limiting
  app/models/       SQLAlchemy models (43 tables)
  app/services/     Domain logic: pricing, inventory, sales, credit, …
  app/api/v1/       HTTP routes and response shaping
  app/workers/      Scheduled reminders, alerts and trial expiry
  alembic/          Migrations
  tests/            257 tests
web/                Next.js app: home, sales and receipts, products and import,
                    stock (receive, adjust, transfer, ledger), online shop
                    (storefront, enquiries, proformas), reports, credit,
                    contacts, notifications, settings, storefront, share links
mobile/             Flutter app for the shop floor, works offline
  lib/core/offline/ Outbox, sync service and catalogue cache
  test/             35 tests
docs/               Architecture, decisions and roadmap
```
