# Architecture

How the system is put together, and the reasoning behind the parts that were
not obvious. This complements the PRD rather than repeating it.

## Shape

```
  Browser (Next.js)   Phone (Flutter)   Storefront visitor
        │                   │                   │
        │  Bearer token     │  Bearer token     │  no token
        │                   │  + local outbox   │
        ▼                   ▼                   ▼
  ┌──────────────────────────────────────────┐
  │  FastAPI  ·  /api/v1                     │
  │  ┌────────────────────────────────────┐  │
  │  │ routers   request/response shaping │  │
  │  ├────────────────────────────────────┤  │
  │  │ services  every business rule      │  │
  │  ├────────────────────────────────────┤  │
  │  │ models    43 tables, tenant-scoped │  │
  │  └────────────────────────────────────┘  │
  └──────────────┬───────────────┬───────────┘
                 │               │
          PostgreSQL         Worker process
                             (reminders, alerts,
                              trial expiry)
```

Business rules live in `app/services/` and nowhere else. Routers translate HTTP
to service calls and decide what the caller may see; models hold shape and
constraints. Both clients talk to the same service layer through the same API,
so rules are never duplicated per client.

The Flutter app adds one thing the web app does not have: a durable outbox, so
a sale can be captured with no connection and replayed later. It does not add
business rules — the server still decides whether a queued sale is valid. See
[the mobile README](../mobile/README.md) for the conflict policy, and
[decisions.md](decisions.md) for why each choice was made.

## The five decisions that explain the rest

### 1. Tenant isolation is a call-site discipline, not a convention

Every operational table carries `tenant_id`, and reads go through
`tenant_query(Model, tenant_id)` or `get_tenant_object(...)` in
`app/core/tenancy.py`. Neither can be called without a tenant id, so omitting
the filter is something you can see in a diff rather than something that
silently leaks.

A row belonging to another business is reported as **not found**, never
forbidden. A 403 would confirm that the id exists somewhere, which is itself a
leak.

The tenant comes from the signed token. The `X-Tenant-Id` header can only
*select among* businesses the user actually belongs to — `test_tenant_isolation.py`
includes a forged-header case.

### 2. Authorisation checks permissions, never roles

`app/core/permissions.py` defines 46 granular permissions and bundles them into
the four default roles. Application code calls `ctx.require(Permission.X)` and
never asks "is this user a manager?". Custom role bundles were deferred to a
later release, but because no call site assumes a role, adding them will not
require touching business logic.

Per-user grants and revocations sit on top of the bundle, so one cashier can be
given cost visibility without inventing a new role.

### 3. Stock is an append-only ledger with a proven cache

`StockMovement` is the source of truth: every change is a signed row with a
reason, an actor, a timestamp, the resulting balance and a link to whatever
caused it. Nothing updates or deletes a movement.

`StockBalance` caches the current quantity per (variant, location) and is
written **only** by `post_movement`, inside the same transaction as the movement
that changes it. On PostgreSQL the balance row is locked with
`SELECT ... FOR UPDATE` so two concurrent sales cannot both read the same
starting quantity.

Because a cache can drift, `reconcile_balances` recomputes every balance from
the ledger and returns the differences. It is exposed at
`GET /api/v1/stock/reconciliation` and asserted in the test suite, including a
test that deliberately tampers with a balance and checks the discrepancy is
reported.

Negative stock is refused unless the business has explicitly enabled it, and
every negative posting writes an audit record.

A transfer is three steps — draft, dispatch, receive — and stock in transit is
real. If fewer units arrive than were dispatched, receiving posts the full
dispatched quantity in and then an explicit *loss* movement out at the
destination. The units that left the source are all accounted for, the
destination holds exactly what was counted in, and the discrepancy is a ledger
row with a reason, an actor and a timestamp rather than a note on the transfer.

### 4. One payment ledger

The PRD warns against maintaining the same balance independently in several
tables. So there is exactly one money table, `payments`, and a row may point at
the sale or purchase it was taken against **and** the credit transaction it
settles.

A credit sale therefore works like this: the receivable's `original_amount` is
the full sale total, the money taken at the till is a single `Payment` row
linked to both the sale and the receivable, and
`CreditTransaction.amount_paid` is a cached sum of those rows that
`recalculate()` refreshes from the ledger. The sale's "amount paid" and the
receivable's "amount paid" are the same rows read twice, so they cannot
disagree — `test_the_till_payment_is_not_counted_twice` asserts exactly that.

One payment settles one credit transaction today. A `PaymentAllocation` table is
the extension point if one payment ever needs to clear several invoices.

### 5. Credit status is derived, never assigned

`derive_status()` takes balance, due date and cancellation state and returns the
status. Nothing assigns a status by hand, so a transaction with money
outstanding can never read as paid — there is a test that sets `status = PAID`
directly and asserts the derived value disagrees.

The due-date rules follow the PRD closely, and the distinction matters:

- A due date is **optional**.
- A balance with no due date is *outstanding* but never *overdue*, however long
  it has been open. Elapsed time alone does not make a debt late.
- A balance becomes overdue only once its due date has **passed** and money is
  still owed. Due *today* is not yet overdue.
- Changing a due date reschedules reminders and recomputes the state, and is
  audited.

## Document numbers come from a locked sequence

`S-2026-000042`, `P-2026-000007`, `PF-2026-000003`: each business, document
kind and year has one row in `document_sequences` holding the last number
issued. `next_number` reads it under `SELECT … FOR UPDATE`, so two sales
posted at the same moment queue behind each other instead of both computing
the same number and one of them failing on the unique constraint. SQLite has
no row locks but serialises writers, which gives the same result.

The first number issued after an upgrade seeds the row from the highest
number already in the table, so a database that used the old count-based
scheme carries on where it left off. The unique constraint on
`(tenant_id, number)` stays as the backstop, and a PostgreSQL-only test starts
two transactions at once and checks that the second waits.

## The business's clock, not the server's

Timestamps are stored in UTC. A business lives in its own timezone — Addis
Ababa is UTC+3 — and every calendar question is asked in that zone
(`app/core/clock.py`):

- "today" on the dashboard, and the day a sale or purchase was issued on;
- the start and end of a report period, and which day each sale belongs to
  in the sales-by-day report;
- whether a balance is due today or overdue;
- when the worker considers a reminder due, per business.

Without this a sale at 01:00 in Addis Ababa lands on the previous day's report
and a balance due today reads as due tomorrow until 03:00. The Ethiopian
calendar is a display question layered on top of this and is still to come;
storage does not change for it.

## Snapshots, so history stays true

A sale line stores the description, unit price, discount, tax rate and **unit
cost** as they were at the moment of sale. Editing a product's price or cost
later changes nothing about past sales, and profit reporting uses the cost that
actually applied. `test_sale_snapshots_price_and_cost_so_later_edits_do_not_rewrite_history`
covers this.

## Markup and margin are different things

The interface may say "target profit", but the system always records which
calculation applies:

- markup: `price = cost × (1 + rate)` — 25% on 100 gives **125**
- margin: `price = cost ÷ (1 − rate)` — 25% on 100 gives **133.33**

`GET /api/v1/pricing/suggest` returns the suggested price *and* an explanation
naming the basis and the rule that produced it, so nobody has to guess.

Rules resolve most-specific-first: product override → category rule → business
default.

## Landed cost and shared costs

Per-unit landed cost is purchase price plus transport plus other costs. When a
purchase carries costs that apply to several products, `allocate_shared_cost`
splits them by value (default) or by quantity, and pushes any rounding
difference onto the largest line so the parts always sum back to the total
exactly.

Receiving updates a weighted average cost: stock already on hand keeps its cost,
the new units bring theirs.

## Idempotency

Sales, purchases, stock movements and credit payments all accept an idempotency
key, unique per business. The service checks for an existing record first, and a
database unique constraint is the backstop if two requests race. Composite keys
are derived for the movements a single sale generates
(`sale:<id>:<line index>`), so retrying a sale cannot post its stock twice.

This is what makes offline capture safe. The mobile app generates the key when
a sale is *captured*, not when it is sent, so a queued sale replayed after an
ambiguous failure returns the record the server already created instead of
producing a second one. Without server-side idempotency, an offline queue would
be a duplicate-sales generator.

## Portability, and why the tests run on two databases

PostgreSQL is the production database. The models avoid PostgreSQL-only types —
`GUID` and `UTCDateTime` in `app/core/db.py` adapt per dialect — so the suite
also runs on in-memory SQLite in about a minute, which keeps the feedback loop
short.

SQLite is not sufficient on its own: it ignores `VARCHAR` length limits and has
no row locking. Running the same suite against PostgreSQL caught a real bug —
composite idempotency keys were 81 characters in an 80-character column, which
SQLite accepted and PostgreSQL rejected. CI runs both.

## Audit trail

`AuditEvent` is append-only and records privileged and financially material
actions: stock adjustments, sale voids, payments and reversals, due-date
changes, credit cancellations, credit-limit overrides, role changes, negative
stock, and platform-admin support access.

Support access deserves a note. There is no hidden impersonation. A platform
administrator must give a written reason, the grant is recorded in the
business's own audit log *before* a token is issued, and the token is
short-lived. It is also **read-only**: the token carries a `support` claim, the
API keeps only the `*:view` and `report:*` permissions of the borrowed
membership, every posting route refuses it, and the `X-Tenant-Id` header cannot
move it to another business. The web app shows a banner for the whole session.

## Rate limiting and account recovery

Sign-in, platform sign-in, password reset and the public storefront's
submissions are rate-limited (`app/core/ratelimit.py`): a sliding window per
client address, and per account for sign-in so one guessed address cannot lock
out an office behind one NAT. The window lives in process memory, which is
right for the single-container deployment the PRD starts with; a multi-worker
deployment puts the same limits at the reverse proxy or swaps the window for a
Redis-backed one behind the same interface.

Password reset issues a single-use token with an expiry and hands the link to
the email transport. The reply is the same whether or not the address exists.

## What the storefront can and cannot do

The public endpoints under `/api/v1/public/` take no token. Every lookup starts
from a published shop slug or an unguessable share token, so there is no path
from a public request to another business's data.

An enquiry or a proforma **never** reserves or reduces stock. A customer
accepting a proforma records intent and nothing more; only the explicit
conversion step posts a sale and moves stock. The public proforma page says in
plain words that it is not a receipt.

## Trial expiry

When a trial lapses the business becomes read-only: existing data stays visible
and untouched, new posting is refused with a clear message. Nothing is deleted.
`require_writable` is the dependency that enforces it on posting routes.

## Where extension points are

| Need | Where |
| --- | --- |
| S3 or other object storage | Implement `StorageBackend` in `app/services/storage.py` |
| Real email delivery | Implement `EmailSender` in `app/services/notifications.py` |
| Telegram or SMS reminders | Add a `ReminderChannel` and a branch in `run_due_reminders` |
| Shared rate limits across workers | Implement the window behind `RateLimiter` in `app/core/ratelimit.py` |
| One payment across many invoices | Add `PaymentAllocation`; `Payment` already has the links |
| Custom role bundles | `Role` and `RolePermission` are already per-tenant rows |
| A mobile client | Same API; the OpenAPI document generates typed models |
