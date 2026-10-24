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

That flexibility is also why cost visibility cannot be inferred from another
permission. Every default role holding `purchase:view` also holds `cost:view`,
so the purchasing routes could read a purchase — unit cost, landed cost,
allocated transport — while checking only the former. One grant separates the
two. Reading a purchase now requires both, and `COST_BEARING_FIELDS` in
`app/core/tenancy.py` names every field that reveals cost or profit so
`test_permissions.py` can sweep each route and fail if a new one forgets,
rather than relying on whoever adds the next endpoint to remember. Receiving a
purchase is the exception, and says so: the caller supplies the costs, so the
response tells them nothing they did not send.

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

## Returns are documents, not edits

A sale keeps the prices, discounts, tax and cost snapshots it was agreed at. A
return is a separate numbered document against it (`SR-2026-000001`), holding
what came back, when, who took it and what it was worth. Three things have to
agree, so each is derived rather than supplied:

- **Goods.** Returned units come back on the stock ledger as `SALE_RETURN`.
  Units not fit to sell again come back and are then written off as `LOSS`, so
  the damage is a movement with a reason and an actor rather than a silent
  absence — the same choice made for transfer shortfalls.
- **Value.** Carried from the sale's own line, pro-rata for a part return. The
  return that takes the *rest* of a line takes exactly what is left, so
  returning a line in two goes gives back precisely what returning it in one
  would and no cent is lost to rounding.
- **Money.** An outstanding balance on the sale absorbs the value first; only
  what is left is handed back, and never more than was actually taken for that
  sale. Settling a receivable is a `Payment` row with method `credit_note`
  against the receivable alone — the single payment ledger still holds every
  movement of value, and cash reports can tell it from money through the till.

Two consequences worth stating. `Sale.amount_paid` nets money out against
money in, so a refund does not read as a further payment; and
`credit.recalculate` sums with a sign relative to the direction that settles
that kind of balance, so a refund reduces what is settled instead of adding to
it — a receivable settles with money in, a payable with money out.

A sale with returns cannot be voided: voiding reverses the whole sale's stock
and money, which on top of a return would reverse the returned units twice.

## Plan limits

A plan may cap branches, staff accounts and products. `None` means unlimited,
and a business on no plan at all — a trial that has not chosen one — has no
caps: a limit applies because a plan says so, never by default.

A business pushed over a cap by a downgrade keeps everything it has. Only the
next addition is refused, which is the same promise trial expiry makes: nothing
is deleted or hidden because of billing. An outstanding invitation holds a
seat, or a three-seat business could invite thirty people and have them all
walk in; deactivating a branch, product or member frees its slot, which is how
a business makes room without deleting history.

A spreadsheet import is checked for the whole batch before any row is written,
so a long file is refused as an import rather than stopping part-way and
reporting a single product. The preview reports the same thing, so the wizard
can say so before anyone confirms.

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

## One lookup per operation, not per line

A sale, purchase, transfer or stock count posts one movement per line, and
`post_movement` needs two things every time: the line's variant (for
`track_stock` and the product id) and the operation's location (for its
branch). Resolving those inside the loop made the query count grow about five
times faster than the number of lines — and the variant's product was
lazy-loaded on top, one row at a time.

`MovementRefs` resolves them once for the whole operation and is passed down to
each posting. Every object still comes through `tenant_query`, so the tenant
check is exactly where it was; it happens once per operation instead of once
per line. Constructed with no ids it behaves as before — each object fetched on
first use, then reused — so callers posting a single movement are unaffected.

At thirty lines:

| Operation | Queries before | After |
| --- | --- | --- |
| Post a sale | 285 | 168 |
| Receive a purchase | 322 | 204 |
| Draft a transfer | 41 | 12 (flat) |
| Dispatch a transfer | 184 | 126 |
| Receive a transfer | 214 | 156 |
| Post a stock count | 184 | 126 |

What remains per line is the work a line genuinely needs: its idempotency
check, the `SELECT … FOR UPDATE` on its balance row, and the writes. The
idempotency keys could be batch-checked too, which would save one more query a
line, but that check is what makes offline replay safe and it is not worth
putting a cache in front of for the sake of fifteen percent.

`tests/test_query_counts.py` pins the shape rather than a number: adding lines
may add the writes a line needs, but it must not add another read of the
catalogue or the location. An absolute budget would break on any unrelated
query change and teach people to raise the number.

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
from a published shop slug, an unguessable share token, or the unguessable id
of a file flagged public, so there is no path from a public request to another
business's data.

A visitor browses the catalogue by category, opens a product page with the
photo the seller uploaded, fills a basket that lives in their own browser, and
checks out by asking for a proforma. The request becomes a numbered proforma
in the `requested` state, priced from the catalogue, linked to a customer
record matched by phone number; staff who handle proformas are notified. The
visitor gets the share link straight away, and it doubles as their tracking
page: the request first, the priced proforma once the seller sends it, and the
outcome after that.

The seller's review is a real step, not a formality. Lines, prices, discounts,
delivery and terms can be changed while a proforma is requested, a draft, or
sent but unanswered, and a product line without a price cannot be sent. Once
the customer has accepted, the numbers are what was agreed and stay as they
are.

An enquiry, a request or a proforma **never** reserves or reduces stock. A
customer accepting a proforma records intent and nothing more; only the
explicit conversion step posts a sale and moves stock. The public proforma
page says in plain words that it is not a receipt.

Product photos are the one kind of upload served without a token. An asset is
served only when it is flagged public, its id is unguessable, and a new upload
always gets a new id, so the URL can be cached indefinitely.

## The marketplace, and the one place tenants are crossed

Every shop runs independently and can publish its own storefront at
`/shop/<slug>`. The marketplace is the other thing: one catalogue at `/market`
holding the products of every shop that opted in, so a buyer can compare
vendors and fill one basket from several.

That crosses the line the rest of the system rests on. Everywhere else a read
goes through `tenant_query(Model, tenant_id)`, which cannot be called without
a tenant id. The marketplace has to read across shops by definition, so the
crossing is made **once**, in `app/services/marketplace.py`, and `tenant_query`
itself names that module as its only exception. The crossing is narrow by
construction:

- it reads products, variants, categories, stores and stock balances, and
  nothing else — no customer, credit, sale, purchase, cost or audit row is
  reachable from a marketplace request;
- it returns a projection built field by field, never a model instance a
  caller could walk relationships from;
- stock is reduced to a boolean, so a rival cannot watch a shop's quantities
  by polling;
- it lists only shops that opted in **and** can answer. A suspended shop, or
  one whose trial has lapsed into read-only, cannot reply to a request, so
  soliciting it would waste the buyer's time.

Listing is opt-in at two levels and both default to off: the shop joins
(`OnlineStore.list_on_marketplace`) and marks the products it wants listed
(`Product.on_marketplace`). Deliberately separate from `is_published`, which
controls the shop's own page: running your own storefront is not the same
decision as appearing next to competitors, and a shop may want either, both or
neither.

## One basket, several shops

A buyer's cross-shop basket becomes one `MarketplaceRequest` — the only
operational table with no `tenant_id`, because it belongs to the buyer rather
than to any shop — and one `Quotation` per shop, each priced from that shop's
own catalogue and each following the review-and-send lifecycle it already had.

Three rules hold it together:

- **Each shop sees only its own part.** A quotation records that it came from
  the marketplace, because knowing the buyer is probably asking others is fair
  and useful to a seller. It does not record who else was asked, and nothing
  joins from a quotation to its siblings.
- **The buyer sees everything**, through one tracking link given at once.
  Acceptance is per shop, so they can take one price and leave another.
- **Nothing reserves stock**, exactly as for a single-shop request.

The request's overall status is derived from its quotations, exactly as a
customer's credit status is derived from their transactions. A stored column
would have to be rewritten every time any one of several shops answered, and
would read "open" forever the first time that was missed. The only thing stored
about a request's own progress is `withdrawn_at`, which no quotation can imply.

The buyer's reference (`MR-2026-DEDDPF`) is random rather than sequential.
Tenant documents get their numbers from a locked per-business row, but a
request spans businesses: a shared sequence would serialise every shop on the
platform behind one lock, and a sequential public reference would tell anyone
who asked for two how many requests the platform handles. Each shop's own
proforma keeps its ordinary sequential number.

Withdrawal cancels the proformas no shop has answered yet and leaves the ones
already sent alone — silently cancelling work a shop has done would be rude,
and the buyer declines those individually. Either way it is written to each
shop's own audit log, with the buyer named as the actor since they have no
account.

## Trial expiry

When a trial lapses the business becomes read-only: existing data stays visible
and untouched, new posting is refused with a clear message. Nothing is deleted.
`require_writable` is the dependency that enforces it on posting routes.

A paid subscription that runs out does exactly the same thing
(`billing.expire_lapsed_subscriptions`). Without that, a shop that stopped
paying would keep the service for good; with a different promise, billing would
be a reason to delete someone's books. It is the same rule, applied to the same
state, for the same reason.

## Billing

A subscription said which plan a shop was on and when its period ended. That is
enough to decide whether to let it in, and not enough to run a platform: "which
shops have paid, which owe me, how much is overdue" had no answer.
`SubscriptionInvoice` and `SubscriptionPayment` are that answer, and
`app/services/billing.py` holds the rules.

Neither table is tenant-scoped. The money is between the platform and the shop
rather than inside the shop's own books, so both carry `tenant_id` as a plain
foreign key and sit beside `subscriptions`, which does the same. The platform
reads them across shops as a matter of course; a shop reads its own through one
endpoint that filters explicitly, and can never write to them — the invoice is
the platform's document.

Nothing about the money is stored twice. An invoice holds what was charged and
payments hold what arrived; what is paid, owed, overdue or settled is summed
from those rows on read. A shop gets one invoice a month, so there is nothing to
optimise, and a derived figure cannot disagree with the rows it came from. There
is no `status` or `amount_paid` column to fall out of step — the same reasoning
as the derived credit status and the derived marketplace request status.

A correction keeps the original. A payment recorded in error is reversed, not
deleted; an invoice raised in error is voided, not removed. An invoice with
money against it refuses to be voided at all, because voiding it would leave
that payment belonging to nothing — reverse the payments first, and both
corrections are on the record in the order they happened.

Invoices are numbered per shop, from the same locked-sequence machinery as that
shop's own sales and proformas: `SUB-2026-000001`. A platform-wide sequence
would serialise every shop behind one lock, which is the same reason a
cross-shop marketplace request gets a random reference instead.

The database constraint is a **partial** unique index — one invoice per shop per
period *where `voided_at IS NULL`*. A plain unique constraint would have made a
mistake permanent: voiding is how an invoice raised in error is undone, so the
period has to be billable again afterwards. Both PostgreSQL and SQLite support
partial indexes, and `scripts/demo.sh` migrates SQLite.

### Billing decides access, in one direction only

Paying an invoice in full extends the paid-for period and can bring a shop back
from read-only. It can never lift a suspension. Suspension is a decision about
conduct, and a platform whose sanctions can be bought off has no sanctions; the
money is still recorded and the period still extends, because the shop did pay,
but getting back in takes a deliberate, audited change of status.

Reversing a payment does not take access away either. The invoice goes back to
owing, which is the honest state, but a bookkeeping correction is not a
judgement about a shop — the daily lapse run makes that on the period's own
terms.

The daily run bills before it lapses, so a shop is asked for the next period
while it still has service rather than after it is cut off, and there is always
an invoice waiting to be paid to come back.

## The platform console

`/admin` is the operator's console, and it is a **separate identity** from any
shop (PRD 5.2). The operator signs in at `/platform/login` against
`platform_admins`, and the token is kept under its own key in the browser, so
the console and a shop can be open in the same browser without either signing
the other in or out — a test drives exactly that, because getting it wrong
would be silent and bad.

The console cannot act *as* a shop. Looking inside one goes through support
access, which mints a short-lived, read-only token and records the reason in
that shop's own audit log before handing anything back. Everything else the
operator does — a status change, a plan move, a payment recorded — is written
to the affected shop's log too, which is why the console says so in its footer.

Screens: the money and the shops needing a decision (`/admin`), every shop
(`/admin/shops`), one shop with all its levers (`/admin/shops/<id>`), invoices
across shops (`/admin/billing`), plans (`/admin/plans`), the platform switches
(`/admin/settings`) and the cross-shop trail (`/admin/audit`).

### Switches that do something

`feature_flags` has existed since the first migration and the admin API could
write rows to it, but nothing anywhere read one — so every switch was a note to
self. `app/services/platform_settings.py` is the registry of switches the
system actually enforces, and an unknown key is now refused with the list of
real ones rather than stored as a setting that does nothing.

A flag resolves as: this shop's row, else the platform-wide row, else the
documented default. A missing row is never simply "off", because an empty table
must not disable the platform. The per-shop row winning is what makes "closed
to new shops, except this one" expressible.

Two switches exist, and each is enforced: `registration_open` gates
`POST /auth/register`, which is how the platform goes invitation-only without
touching a shop that already exists; `marketplace_open` gates cross-shop
requests, which pauses the marketplace without unlisting anybody's products.

## Where extension points are

| Need | Where |
| --- | --- |
| S3 or other object storage | Implement `StorageBackend` in `app/services/storage.py` |
| Real email delivery | Implement `EmailSender` in `app/services/notifications.py` |
| Telegram or SMS reminders | Add a `ReminderChannel` and a branch in `run_due_reminders` |
| Shared rate limits across workers | Implement the window behind `RateLimiter` in `app/core/ratelimit.py` |
| One payment across many invoices | Add `PaymentAllocation`; `Payment` already has the links |
| Custom role bundles | `Role` and `RolePermission` are already per-tenant rows |
| A new permission | Add to `Permission` and the role bundles, **and** write a migration backfilling `role_permissions` — those rows are written once per business at registration, so a new permission is otherwise invisible to every business that already exists, owners included |
| A mobile client | Same API; the OpenAPI document generates typed models |
