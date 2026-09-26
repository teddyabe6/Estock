# Roadmap

What is built, what is next, and what is deliberately left for later. Release
scope is controlled: a feature listed for a later release should not arrive in
MVP merely because it is convenient to add.

## Built (MVP)

Everything in PRD section 3.1 except the items listed under *Next* below.
The MVP acceptance gate in PRD section 24 is covered by automated tests in
`backend/tests/test_workflows.py`:

| Acceptance criterion | Test |
| --- | --- |
| A new owner can register, create a business and branch, add products and sell | `test_registration_creates_a_ready_to_use_business`, `test_a_product_needs_only_a_name` |
| A tenant can add branches and users while staying isolated | `test_tenant_isolation.py` (17 tests) |
| Stock stays consistent across sales, receipts, transfers, returns, adjustments | `test_inventory.py`, `test_cached_balances_reconcile_with_the_ledger` |
| Credit sales and purchases with partial payments and accurate due states | `test_credit.py` (36 tests) |
| Reminders and dashboards work without messaging customers | `test_reminder_delivery_notifies_authorised_staff_only` |
| Publish online and receive an enquiry from the same catalogue | `test_the_storefront_uses_the_same_catalogue_and_stock`, `test_an_enquiry_reserves_no_stock` |
| Share a proforma without posting a sale or reducing stock | `test_a_proforma_is_not_a_sale_until_it_is_converted` |
| Reports agree with transactions and respect permissions | `test_permissions.py`, `test_profit_figures_are_withheld_without_cost_view` |
| Trial expiry applies the policy without deleting data | `test_an_expired_trial_restricts_access_without_deleting_data` |
| Security: rate limiting, account recovery, read-only support access | `test_repeated_failed_sign_ins_are_rate_limited`, `test_password_reset_round_trip`, `test_support_access_can_look_but_not_touch` |
| Concurrent sales, duplicate submissions and retries | `test_concurrency.py`, including a PostgreSQL-only test of two transactions numbering at once |
| A transfer received short keeps every unit accounted for | `test_a_transfer_shortfall_is_posted_as_a_loss_movement` |

The web app now covers every MVP workflow end to end: onboarding, import,
products, sales and receipts, receiving with supplier credit, adjustments and
transfers, the online shop with enquiries and proformas, credit with payments
and follow-up, reports with CSV export, contacts, notifications and settings.
The mobile app covers sales (cash or credit, with a customer picker that works
offline), stock lookup, credit and the shop.

## Also built (ahead of the PRD's own schedule)

Two items the PRD lists for later were built because a shop floor needs them:

- **The Flutter app** (PRD section 18 lists it in the architecture): sign-in,
  home, point of sale, stock, online shop, credit and a pending-sync screen.
- **Offline sale capture and sync** (PRD V2): a durable outbox, replay on
  reconnect, and a stated conflict policy. See
  [mobile/README.md](../mobile/README.md).

Offline sync was scoped deliberately narrowly. What is built is offline
**capture of sales**, because that is the operation a shop cannot postpone.
Offline receiving, transfers and stock counts are not built: those are usually
done at a desk, and each needs its own conflict answer.

## Next — completing MVP

Ordered by what a first real shop would miss soonest.

1. **Amharic translations.** Ethiopic text renders correctly everywhere —
   database, API, web and mobile, with the font bundled in the app — and there
   are tests. What is missing is translating the interface strings themselves
   and a locale switch.
2. **Email delivery.** `EmailSender` is a one-class swap once a provider is
   chosen. Until then password-reset links are written to the API log rather
   than sent, and the owner passes an invitation link on by hand: the Team
   page shows it for every pending invitation with a copy button.
3. **Receipt and proforma PDFs.** Both pages print cleanly today; a server-side
   renderer would make sharing more reliable on low-end phones.
4. **Product images.** `FileAsset` and the storage interface exist; an upload
   endpoint and the storefront's image slot do not yet.
5. **Enforce plan limits.** `SubscriptionPlan` carries max branches, users and
   products; nothing enforces them yet.
6. **Barcode scanning with the camera.** The sale screens already accept
   scanner input (a scanner types and presses Enter); using the phone camera
   needs a plugin and a permissions flow.
7. **Stock counts in the web app.** The API has the count workflow (start,
   record lines, review variances, post); the web app does not yet have a
   screen for it.

## V1.5

Advanced supplier management, purchase orders, expenses, customer-specific and
wholesale pricing, discount approval workflows, advanced stock counting
(blind counts, partial counts by category), richer storefront configuration,
and report exports.

## V2

Richer barcode workflows, delivery integrations, customer loyalty, payment
gateway integration, digital receipts, and additional messaging channels
including customer-facing reminders.

Offline capture of **sales** is done. What remains of offline-first:

- Offline receiving, transfers and stock counts, each needing its own conflict
  answer.
- Offline credit: deliberately excluded for now, because showing a stale
  balance while deciding whether to extend more credit is worse than showing
  nothing.
- A background sync worker that drains the outbox while the app is closed.

## V3

AI business assistant, reorder suggestions, demand forecasting, automated
customer communications, marketplace and discovery, accounting integrations.

## Known gaps worth naming

- **Refunds** are not a first-class flow. A sale can be voided in full; partial
  returns to stock with money back are not yet modelled.
- **Reminder scheduling** runs hourly from a single worker. That is right for
  the current scale and will need a proper queue before it is not.
- **Rate limiting** is per process. Sign-in, password reset and storefront
  submissions are limited in memory, which is right for one container; a
  multi-worker deployment needs the same limits at the reverse proxy or a
  shared window behind the same interface.
- **Web tests** are a browser smoke run by hand against the demo data (sign in,
  sell, receipt, credit follow-up, receive stock, edit and import products,
  every page as owner and cashier, phone width). It is not yet automated in CI.
- **The mobile app has no automated end-to-end test.** The offline round-trip
  was verified by hand against a live API (capture offline, reconnect, confirm
  the sale posted). The outbox and sync logic have unit tests; the UI path does
  not have an integration test yet.
- **Backups** are a deployment concern and are not automated in this
  repository. The PRD requires tested restoration before production.
