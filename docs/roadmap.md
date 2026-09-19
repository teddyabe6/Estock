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

## Next — completing MVP

Ordered by what a first real shop would miss soonest.

1. **Amharic translations.** The interface is translation-ready and Amharic
   text round-trips correctly through the database and API (tested). What is
   missing is the strings and a locale switch.
2. **Flutter mobile app.** The API is the contract; generate typed models from
   `/api/v1/openapi.json`. Start with the sales screen and stock lookup — the
   two things a shop floor needs on a phone.
3. **Receipt and proforma PDFs.** Both pages print cleanly today; a server-side
   renderer would make sharing more reliable on low-end phones.
4. **Email delivery.** `EmailSender` is a one-class swap once a provider is
   chosen.
5. **Enforce plan limits.** `SubscriptionPlan` carries max branches, users and
   products; nothing enforces them yet.

## V1.5

Advanced supplier management, purchase orders, expenses, customer-specific and
wholesale pricing, discount approval workflows, advanced stock counting
(blind counts, partial counts by category), richer storefront configuration,
and report exports.

## V2

Offline-first transaction capture and synchronisation, richer barcode
workflows, delivery integrations, customer loyalty, payment gateway
integration, digital receipts, and additional messaging channels including
customer-facing reminders.

Offline-first is the largest single piece of work here. The stock ledger is
already append-only and every posting takes an idempotency key, which is the
right foundation, but conflict resolution for concurrent offline sales needs
designing before any code.

## V3

AI business assistant, reorder suggestions, demand forecasting, automated
customer communications, marketplace and discovery, accounting integrations.

## Known gaps worth naming

- **Refunds** are not a first-class flow. A sale can be voided in full; partial
  returns to stock with money back are not yet modelled.
- **Reminder scheduling** runs hourly from a single worker. That is right for
  the current scale and will need a proper queue before it is not.
- **Rate limiting** is not implemented at the application layer; it belongs at
  the reverse proxy for now, and the PRD's requirement should be revisited
  before public launch.
- **Backups** are a deployment concern and are not automated in this
  repository. The PRD requires tested restoration before production.
