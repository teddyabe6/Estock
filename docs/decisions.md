# Decisions register

PRD section 25 lists twelve open decisions. None of them could be invented, so
each one below records **what the system does now**, whether that is a safe
default or a placeholder, and what still needs an answer from the business.

The rule applied throughout: where a decision was unresolved, choose the
behaviour that is conservative, visible and reversible, and make it
configurable rather than assumed.

## Needs a business or legal answer before production

These are not technical questions and the code cannot settle them.

| # | Question | What the system does now | What is needed |
| --- | --- | --- | --- |
| 1 | Tax, VAT, invoice and receipt requirements | Tax is a per-product rate with a business-level default, applied after discount. No VAT claims are made anywhere. | Confirmed Ethiopian VAT registration thresholds, invoice format and receipt wording, from a qualified local adviser. Do not claim compliance until then. |
| 2 | Hosting, data residency, privacy obligations | Self-hosted PostgreSQL; file storage behind an interface with a local-disk implementation. | A decision on where data may live, and what the retention and deletion policy is. |
| 3 | Email delivery, Telegram integration, delivery guarantees | `EmailSender` logs instead of sending, so nothing depends on a provider. Telegram sharing is a prepared share URL the user sends themselves, not a bot. | Choice of email provider, and whether Telegram should become a bot integration. |
| 4 | Trial length, plan limits, prices, grace period | 14-day trial, changeable per business by a platform admin. Plan records carry limits but they are not yet enforced. | Commercial decisions on pricing, limits and grace period. |

## Decided, with a documented default

| # | Question | Decision taken | Why | How to change it |
| --- | --- | --- | --- | --- |
| 5 | Can stock go negative, and who approves? | **No by default.** A sale that would drive stock below zero is refused with the available quantity in the message. A business can enable it as an explicit setting; every negative posting is then audited. | Silent negative stock hides a counting problem and corrupts valuation. Refusing is recoverable; a wrong balance is not. | `allow_negative_stock` on the business; changing it is audited. |
| 6 | How are shared purchase costs allocated? | **By value** by default, **by quantity** as an option. The method used is stored on the purchase. Rounding differences go to the largest line so the parts always sum to the total. | By value suits transport on mixed-value loads; by quantity suits uniform goods. Recording which was used means a landed cost can always be explained. | `cost_allocation_method` per purchase. |
| 7 | Does a credit sale need a named customer? | **Yes by default.** Anonymous credit can be enabled per business. | A receivable with no counterparty cannot be chased. Businesses that genuinely sell on trust to regulars can opt in. | `require_customer_for_credit` on the business. |
| 8 | Overpayment, refund, cancellation, reversal policy | **Overpayment is refused** and the error states the exact balance. A payment recorded in error is *reversed*, not deleted: the row stays, marked reversed with a reason, and balances recompute. A sale is *voided*, not deleted, with compensating stock movements and a reason. A credit balance is *cancelled*, not removed. | The PRD requires that financial history is never silently discarded. Refusing overpayment surfaces the mistake at the moment it is made. | Overpayment can be allowed per payment by a user holding `credit:limit_override`. Refunds as a first-class flow are still to be designed. |
| 9 | Can quotations be accepted online, and does that affect stock? | A customer can accept or decline through the share link. Acceptance **records intent only** — no sale, no reservation, no stock movement. A separate, explicit conversion posts the sale. | The PRD is firm that a proforma must not be treated as a sale. Reserving stock on acceptance would let anyone with a link deplete availability. | Reservation would need a decision on how long a hold lasts and who may release it. |
| 10 | Do transfers need dispatch and receipt confirmation? | **Yes.** A transfer is drafted, dispatched (stock leaves the source) and received (stock arrives at the destination). Receiving less than was sent is recorded as a discrepancy and does not invent the missing units at the destination. | Stock in transit is real. Moving it in one step hides losses between branches. | Single-step transfer would be a new endpoint, not a change to this one. |
| 11 | Supported spreadsheet formats, limits, duplicate matching | `.xlsx` and `.csv`, up to 5,000 rows per file. Duplicates are matched on SKU and barcode within the business and flagged, not merged; a matching name with no code is reported as a *possible* duplicate. Nothing is written until every row has been validated. | Matching on name alone would merge genuinely different products. Reporting and letting the user decide is safer than guessing. | `MAX_IMPORT_ROWS`; the matching rules live in `validate_import`. |
| 12 | Ethiopian calendar interaction model | **Not implemented.** All dates are stored and computed as Gregorian, in UTC for timestamps and as plain calendar dates for due dates. | The PRD asks for it to be "designed carefully". A half-done calendar that shifts a due date by a day is worse than none. Getting the storage right first means display can be added without touching stored data. | Add a display-layer conversion; storage should not change. |

## The offline conflict policy

The PRD puts offline-first in V2 and does not say what should happen when two
devices disagree. Offline **sale capture** is now built, so that question needed
an answer. The one taken:

| Question | Decision | Why |
| --- | --- | --- |
| Is an offline sale final? | No — it is **provisional** until the server accepts it, and the interface says so. | A sale that has not reached the business records is not in the books, and pretending otherwise is how stock and cash drift apart. |
| Two phones sell the last unit offline; what happens? | The first to sync wins. The second is refused with `insufficient_stock`, marked **rejected**, and shown to a person. | The server is the only place that knows real stock. The app never silently drops the sale, and never invents a correction: what to do about a sale that cannot be posted — refund, back-order, or sell something else — is a business decision. |
| Could a retry post the same sale twice? | No. The idempotency key is generated when the sale is **captured**, not when it is sent, so every replay carries the same key and the server deduplicates. | This is the guarantee that makes retrying after an ambiguous failure safe. |
| In what order do queued sales replay? | Oldest first, strictly. | So the server draws stock down in the order the shop actually sold. |
| What is cached for offline use? | The catalogue and the session. **Not** credit balances. | A stale balance shown to someone deciding whether to extend more credit is worse than showing nothing. |
| Does signing out discard unsynced work? | No. It stays on the device and replays after signing in again. | Unsynced work is the shop's money. |

What is deliberately **not** offline: receiving, transfers and stock counts.
Those are usually done at a desk, and each needs its own conflict answer rather
than being swept in by analogy.

## Decisions made while building that the PRD did not raise

| Decision | Reasoning |
| --- | --- |
| Fonts are bundled in the mobile app, not fetched from a CDN | Without this the app renders **no text at all** when the font CDN is unreachable — precisely the situation it is built for. Amharic also needs Ethiopic glyphs a Latin-only default font does not carry. |
| Every product owns at least one variant, created implicitly | Stock, sales and pricing then have exactly one shape to handle, while the API still accepts a product with nothing but a name. The alternative — nullable variant references everywhere — invites exactly the kind of bug tenant isolation and stock accuracy cannot afford. |
| A row from another business returns 404, not 403 | A 403 confirms the id exists somewhere. |
| "Block" credit-limit behaviour cannot be overridden | Three behaviours exist — warn, require approval, block. If block were overridable it would just be "require approval" with a worse name. |
| A manager can compare branches, but only their own | The report filters to branches the caller is assigned to, so cross-branch visibility is impossible without the assignment. |
| A business must always keep one active owner | Demoting or disabling the last owner would lock everyone out. |
| Reminders are internal only | The PRD is explicit: a generated reminder is not proof anyone was contacted. Every reminder body says so. |
| Money stored at two decimals, quantities at three | ETB has two decimals; three on quantity supports goods sold by weight or volume. Inputs are rounded on write, so the value held in memory is the value stored. |
| Sale numbers restart per business and per year | `S-2026-000001`. A business should not be able to infer platform volume from its own numbering. |

## Deliberately not built

Listed here so the boundary is explicit rather than an oversight. See
[roadmap.md](roadmap.md).

- **Purchase orders, expenses, customer-specific pricing** (PRD V1.5).
- **Offline receiving, transfers and stock counts.** Offline *sales* are built;
  the rest each need their own conflict answer.
- **Payment gateway integration.** Local methods are recorded, not processed —
  the PRD asks for exactly this in MVP.
- **Amharic translations.** Ethiopic text renders correctly end to end —
  database, API, web and mobile — and the mobile app bundles the font for it.
  The interface strings themselves have not been translated.
- **PDF rendering of proformas.** The share page is print-to-PDF ready; a
  server-side renderer was not added.
