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
| 4 | Trial length, plan limits, prices, grace period | 14-day trial, changeable per business by a platform admin. Plan limits on branches, staff and products are enforced: `None` means unlimited, a business on no plan has no caps, and a business pushed over a cap by a downgrade keeps everything it has — only the next addition is refused. | Commercial decisions on pricing, the numbers themselves and the grace period. |

## Decided, with a documented default

| # | Question | Decision taken | Why | How to change it |
| --- | --- | --- | --- | --- |
| 5 | Can stock go negative, and who approves? | **No by default.** A sale that would drive stock below zero is refused with the available quantity in the message. A business can enable it as an explicit setting; every negative posting is then audited. | Silent negative stock hides a counting problem and corrupts valuation. Refusing is recoverable; a wrong balance is not. | `allow_negative_stock` on the business; changing it is audited. |
| 6 | How are shared purchase costs allocated? | **By value** by default, **by quantity** as an option. The method used is stored on the purchase. Rounding differences go to the largest line so the parts always sum to the total. | By value suits transport on mixed-value loads; by quantity suits uniform goods. Recording which was used means a landed cost can always be explained. | `cost_allocation_method` per purchase. |
| 7 | Does a credit sale need a named customer? | **Yes by default.** Anonymous credit can be enabled per business. | A receivable with no counterparty cannot be chased. Businesses that genuinely sell on trust to regulars can opt in. | `require_customer_for_credit` on the business. |
| 8 | Overpayment, refund, cancellation, reversal policy | **Overpayment is refused** and the error states the exact balance. A payment recorded in error is *reversed*, not deleted: the row stays, marked reversed with a reason, and balances recompute. A sale is *voided*, not deleted, with compensating stock movements and a reason. A credit balance is *cancelled*, not removed. | The PRD requires that financial history is never silently discarded. Refusing overpayment surfaces the mistake at the moment it is made. | Overpayment can be allowed per payment by a user holding `credit:limit_override`. Returns are now a first-class flow — see below. |
| 9 | Can quotations be accepted online, and does that affect stock? | A customer can accept or decline through the share link. Acceptance **records intent only** — no sale, no reservation, no stock movement. A separate, explicit conversion posts the sale. | The PRD is firm that a proforma must not be treated as a sale. Reserving stock on acceptance would let anyone with a link deplete availability. | Reservation would need a decision on how long a hold lasts and who may release it. |
| 10 | Do transfers need dispatch and receipt confirmation? | **Yes.** A transfer is drafted, dispatched (stock leaves the source) and received (stock arrives at the destination). Receiving less than was sent posts the full dispatched quantity in and an explicit **loss** movement out at the destination, so the missing units are a traceable ledger row rather than a note, and the destination holds exactly what was counted. | Stock in transit is real. Moving it in one step hides losses between branches; a shortfall that is only a note is invisible to stock reports. | Single-step transfer would be a new endpoint, not a change to this one. |
| 11 | Supported spreadsheet formats, limits, duplicate matching | `.xlsx` and `.csv`, up to 5,000 rows per file. Duplicates are matched on SKU and barcode within the business and flagged, not merged; a matching name with no code is reported as a *possible* duplicate. Nothing is written until every row has been validated. | Matching on name alone would merge genuinely different products. Reporting and letting the user decide is safer than guessing. | `MAX_IMPORT_ROWS`; the matching rules live in `validate_import`. |
| 12 | Ethiopian calendar interaction model | **Not implemented.** All dates are stored as Gregorian, in UTC for timestamps and as plain calendar dates for due dates. Every calendar question — today, due today, report days — is asked in the **business's timezone** (`Africa/Addis_Ababa` by default), not the server's. | The PRD asks for it to be "designed carefully". A half-done calendar that shifts a due date by a day is worse than none. Getting the storage and the timezone right first means an Ethiopian-calendar display can be added without touching stored data. | Add a display-layer conversion; storage should not change. |

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

## The returns policy

A sale could only be voided in full, so a customer bringing back two of five
bags had no path. Designing returns meant answering these, and the answers are
what the code does:

| Question | Decision | Why |
| --- | --- | --- |
| Does a return edit the sale? | **No.** It is its own numbered document (`SR-2026-000001`) against the sale. | The sale's prices, discounts, tax and cost snapshots are what was agreed. Editing them would rewrite history and change past profit reports. |
| What is a return worth? | What the customer paid for those units, carried from the sale's own line — never recomputed from the catalogue. | The price may have moved since. Refunding today's price for yesterday's purchase is either a loss or a short-change. |
| Part of a line? | Yes, any quantity up to what is still unreturned across every earlier return. | A customer returning two of five bags is the ordinary case. |
| Does rounding drift over several returns? | No. Pro-rata for a part return, but the return that takes the *rest* of a line takes exactly what is left. | Returning a line in two goes must give back the same total as returning it in one. This is the same approach `allocate_shared_cost` takes. |
| Do the goods go back into stock? | Per line. Goods not fit to sell come back on the ledger and are then written off as a **loss**. | Consistent with the transfer-shortfall decision: a discrepancy gets a movement with a reason, an actor and a timestamp rather than a silent absence. The shop still owes the customer either way. |
| Cash or credit? | An outstanding balance on the sale absorbs the value **first**; only what is left is handed back. | Giving cash to someone who still owes money on the same sale pays them twice. |
| Can a refund exceed what was taken? | No. It is capped at the net money actually received for that sale. | The business cannot pay back money it never received. |
| How is a credit settlement recorded? | A `Payment` row with method `credit_note`, against the receivable only. | The single-payment-ledger rule still holds, and an honest method keeps it out of cash takings. It is deliberately not linked to the sale: the sale's balance already falls by the returned value, and counting it twice would look like overpayment. |
| Can a sale with returns be voided? | No, refused with the return numbers. | Voiding reverses the whole sale's stock and money; on top of a return it would reverse the returned units twice. |
| Who may take a return? | `sale:refund`. Owners and managers hold it; a salesperson does **not** by default. | A void and a return are different authorities. Whether a cashier may accept returns is a decision for each shop, made with a per-user grant. |
| What happens to reports? | Returns are shown as their own figures — count, units, value, cost — beside what was sold, and profit takes back both the revenue and the cost of the returned units. | Netting them silently would leave a reader unable to tell a quiet month from a month of returns. Taking back only the revenue would understate profit as badly as taking back neither. |
| Which day does a return belong to? | The day the goods came back, not the day of the sale. | That is when the money moved. |

## Decisions made while building that the PRD did not raise

| Decision | Reasoning |
| --- | --- |
| Fonts are bundled in the mobile app, not fetched from a CDN | Without this the app renders **no text at all** when the font CDN is unreachable — precisely the situation it is built for. Amharic also needs Ethiopic glyphs a Latin-only default font does not carry. |
| Every product owns at least one variant, created implicitly | Stock, sales and pricing then have exactly one shape to handle, while the API still accepts a product with nothing but a name. The alternative — nullable variant references everywhere — invites exactly the kind of bug tenant isolation and stock accuracy cannot afford. |
| A row from another business returns 404, not 403 | A 403 confirms the id exists somewhere. |
| "Block" credit-limit behaviour cannot be overridden | Three behaviours exist — warn, require approval, block. If block were overridable it would just be "require approval" with a worse name. |
| "Require approval" needs an explicit, audited override | Holding `credit:limit_override` is not the same as having used it. The sale is refused until the caller sends `override_credit_limit`, and the override is written to the audit log with who approved it. Before this, anyone with the permission was waved through silently. |
| An invitation never replaces an existing password | A person invited to a second business already has an account. Accepting the invitation activates the membership and keeps their password; only an account that has never signed in takes its password from the invitation. Otherwise an invitation token would have been a way to reset someone's password. |
| Platform support access is read-only | The support token keeps only view and report permissions, is refused by every posting route and is pinned to one business. Support can see what the owner sees and change nothing, and the grant is in the business's own audit log. |
| Payables need `purchase:view` | A salesperson may record customer payments; supplier payables are purchasing data and stay out of reach even by id. |
| Document numbers come from a locked sequence | Counting rows to pick the next number let two concurrent sales pick the same one. A per-business, per-kind, per-year row read under `FOR UPDATE` serialises them, and it seeds itself from existing numbers so an upgraded database continues its numbering. |
| Rate limits live in process memory | Enough for the single-container deployment the PRD starts with, and honest about it: a multi-worker deployment needs the same limits at the proxy or a shared window, and the interface allows the swap. |
| Daily digests are once per person per day | The worker runs hourly; low-stock digests and trial warnings check whether the person was already told today, in the business's day. |
| A manager can compare branches, but only their own | The report filters to branches the caller is assigned to, so cross-branch visibility is impossible without the assignment. |
| A business must always keep one active owner | Demoting or disabling the last owner would lock everyone out. |
| An outstanding invitation holds a seat on the plan | Counting only active members would let a three-seat business invite thirty people and have them all walk in. Deactivating a branch, a product or a member frees its slot, which is how a business makes room without deleting history. |
| A new permission needs a backfill migration | `role_permissions` rows are written once per business at registration, from the bundle in force then. `sale:refund` would have been invisible to every business that already existed — including its owner — so the migration grants it to the owner and manager roles, matching what a business registering today gets. |
| Credit settlement is summed with a sign | A receivable is settled by money in, a payable by money out. A refund moving the other way has to reduce what is settled rather than add to it, so `recalculate` sums against the direction that settles that kind of balance. |
| Reminders are internal only | The PRD is explicit: a generated reminder is not proof anyone was contacted. Every reminder body says so. |
| Money stored at two decimals, quantities at three | ETB has two decimals; three on quantity supports goods sold by weight or volume. Inputs are rounded on write, so the value held in memory is the value stored. |
| A storefront order is a proforma request the seller confirms | The basket is priced from the catalogue so the seller reviews rather than retypes, but no price reaches the customer as a quotation until a person sends it. PRD 14 asks for review by an authorised person, and a shop that hides prices online would otherwise be quoting blind. |
| A visitor's request is matched to a customer by phone number | It is the one identifier a walk-in customer reliably has, and the contacts screens already store numbers in one canonical form. A second request from the same number lands on the same record instead of creating a duplicate. |
| The customer's link is issued at request time | One link shows the request, then the priced proforma, then the outcome, so the customer has one thing to keep and the seller has nothing to send twice. |
| Product photos are public assets by unguessable id | The storefront serves them without a token; only assets flagged public are ever served that way, and a new upload gets a new id so caches never go stale. |
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
- **PDF rendering of proformas and receipts.** Both pages are print-to-PDF
  ready; a server-side renderer was not added.
- **Reserving stock for an accepted proforma.** PRD 13 forbids a request
  reserving stock until a defined fulfilment step exists. Acceptance is
  recorded and the seller is told; stock moves when they convert the proforma
  as the goods go out.
- **A delivery charge on a converted proforma.** A sale has no delivery line,
  so conversion carries the goods only and returns a warning naming the charge
  to record separately. Modelling delivery on sales is a decision for the
  business, not something to invent.
