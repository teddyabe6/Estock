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
| Amharic-ready interface, ETB, Ethiopian phone formats | Interface is translation-ready; translations not yet written |
| Flutter mobile app | Not started — see [docs/roadmap.md](docs/roadmap.md) |
| Offline-first capture, payment gateways, AI assistant | Later releases, by design |

## Quick start

```bash
cp backend/.env.example backend/.env       # then set SECRET_KEY
docker compose up --build
```

- Web app: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

To start with a realistic demo business:

```bash
SEED_ON_START=true docker compose up --build
```

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

## Running without Docker

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL="postgresql+psycopg://estock:estock@localhost:5432/estock"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
alembic upgrade head
python -m app.seed          # optional
uvicorn app.main:app --reload

# Background jobs (reminders, low-stock alerts, trial expiry)
python -m app.workers.scheduler --loop

# Web
cd ../web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 npm run dev
```

## Tests

```bash
cd backend
pytest                       # 219 tests on SQLite, ~1 minute

# Against PostgreSQL, which also exercises the row-locking paths
TEST_DATABASE_URL="postgresql+psycopg://estock:estock@localhost:5432/estock_test" pytest
```

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
