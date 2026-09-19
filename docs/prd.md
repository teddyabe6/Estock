# Product Requirements Document

Ethiopian Shop Management, Inventory, Sales and Ecommerce Platform.

> Converted from the source `.docx` so it can be reviewed and versioned
> alongside the code. The content is unchanged; only the formatting is
> Markdown. See [decisions.md](decisions.md) for how the open decisions in
> section 25 were handled.

AI-agent-ready master specification | Living document | Version 1.0

**Purpose:** define a simple, locally relevant shop-management platform that combines products, inventory, sales, customer and supplier credit, and an online catalogue while remaining extensible. This document is the current source of truth for product scope and implementation decisions. Where a decision is not yet confirmed, it is explicitly marked as configurable, future scope, or an open decision.

## 1. Product Vision and Principles

- Deliver a digital shop assistant for Ethiopian small and medium businesses: easy enough for a shop owner to start using quickly, with robust stock, sales, credit, branch and online-selling capabilities underneath.
- Prioritise clarity and speed over ERP-style complexity.
- Use progressive disclosure: collect only essential information first and reveal advanced fields when needed.
- A business owns its branches, users, catalogue, transactions and settings. Separate businesses must have strict data isolation.
- Use one product catalogue and one inventory source of truth across in-person sales and online channels.
- Build mobile-first workflows while providing a capable web application for owners and managers.
- Design for Ethiopian business practices, ETB, local phone formats, Amharic and English, intermittent connectivity as a future capability, and locally familiar payment methods.
- Do not silently discard financial or inventory history. Corrections should be traceable.

## 2. Target Users and Jobs to Be Done

- Shop owner: set up the business, monitor sales and stock, manage branches and staff, review profit and credit, and control pricing and permissions.
- Branch manager: oversee branch operations, sales, stock, staff and permitted reports.
- Salesperson/cashier: find or scan products, complete sales quickly, accept payments, record credit where permitted, and issue receipts.
- Warehouse/stock user: receive stock, transfer stock, perform counts and record adjustments without necessarily seeing cost or profit data.
- Customer: browse published products, enquire, request a quotation/proforma, and contact the seller.
- Supplier: represented as a business contact for purchasing and payable tracking; no supplier portal is required for the MVP.
- Platform administrator: manage the SaaS platform, subscriptions, tenant support and platform configuration through a separate privileged interface.

## 3. Product Scope and Release Strategy

## 3.1 MVP

- Tenant registration, business profile, first branch creation and staff invitations.
- Roles and permission checks; strict tenant isolation.
- Products, categories, variants/basic units, cost and price fields, opening stock and Excel import.
- Stock movements, receiving, transfers between branches, adjustments, stock counts and low-stock alerts.
- Fast sales workflow with cash, bank transfer, mobile payment, credit and split payment support.
- Customer and supplier records with transaction history.
- Credit receivables/payables, optional due dates, partial payments, internal reminders and dashboard summaries.
- Basic online catalogue publishing from the inventory catalogue, customer enquiry and quotation/proforma request.
- Proforma generation, printable/downloadable PDF and shareable secure link; email sharing, with Telegram sharing as a supported workflow where practical.
- Core dashboards and reports for sales, stock, profitability, branch comparison and credit.
- English and Amharic-ready interface, ETB and Ethiopian phone number support.
- Trial subscription state, expiry handling and platform-admin controls.

## 3.2 Later releases

- V1.5: advanced supplier management, purchase orders, expenses, customer-specific pricing, discount approvals, advanced stock counting, improved ecommerce storefront configuration and more report exports.
- V2: offline-first transaction capture and synchronisation, richer barcode workflows, delivery integrations, customer loyalty, payment gateway integrations, digital receipts and additional messaging channels.
- V3: AI business assistant, reorder suggestions, demand forecasting, automated customer communications, marketplace/discovery capabilities and accounting integrations.
- Release scope must be controlled. A feature listed for a later release must not be added to MVP merely because it is technically convenient.

## 4. Business, Branch and Tenant Model

- A tenant represents one independent business/customer account. Data belonging to one tenant must never be visible or mutable by another tenant.
- A tenant can own multiple branches and optionally warehouses. Branches are locations belonging to that tenant, not separate tenants.
- Registration should create the tenant and a first branch automatically (default name such as “Main Branch”), with the ability to rename it and add locations later.
- Business-wide and branch-specific reporting must be distinguished. Users may be assigned to one, several or all branches according to permissions.
- Every relevant operational record must be tenant-scoped. Branch-level records must also identify their branch where applicable.
- Do not model unrelated businesses as branches of one another.

## 5. Roles, Access and Administration

## 5.1 Tenant roles

- Owner: full tenant-level authority, including settings, branches, users, pricing, credit and reports.
- Manager: configurable operational access for assigned branches, potentially including sales, stock, staff and reports.
- Salesperson/Cashier: sales and customer workflows; no access to purchase costs, profit or business-wide reports unless explicitly granted.
- Stock/Warehouse user: receiving, transfers, stock counts and adjustments as permitted; cost and margin visibility can be withheld.
- Custom roles/permission bundles may follow after MVP, but permission checks must be granular enough to avoid role-based assumptions in application code.

## 5.2 Platform administration

- Platform administrators operate in a separate administrative surface and identity/permission boundary from tenant users.
- Support access to tenant data must be limited, authorised, logged, and preferably time-bound. Do not provide unrestricted hidden impersonation.
- Platform admin capabilities include tenant status, trial/subscription management, feature flags, platform settings and support diagnostics.
- All privileged administrative actions must be audited.

## 6. Onboarding and Setup

- Register/sign in and verify the account using the configured authentication process.
- Enter business name and essential business details.
- Create the first branch automatically and allow the owner to rename it.
- Ask whether the user has products in Excel. Offer a downloadable template and guided column mapping.
- Allow the user to import products or add a first product manually.
- Offer a default pricing rule and explain that it can be changed later.
- Show a useful home screen with setup progress, product count, stock and next recommended actions.
- Avoid requiring tax, warehouse, payment-provider or advanced accounting configuration before the user can record their first product or sale.

## 7. Navigation and UX Requirements

- Keep the primary navigation short. Suggested web navigation: Home, Sales, Products, Stock, Online Shop, Reports and More. Suggested mobile navigation: Home, Sales, Stock, Shop and More.
- Optimise the most frequent actions for a small number of taps.
- Use clear language rather than accounting jargon wherever possible.
- Use progressive disclosure for optional fields such as SKU, barcode, supplier, advanced pricing and descriptions.
- Provide meaningful empty states, inline validation, confirmation for destructive/high-impact actions and clear success/error feedback.
- Show only information the current user is authorised to see.
- Support responsive layouts and accessible form controls.

## 8. Product Catalogue and Pricing

## 8.1 Product fields

- Required MVP field: product name. Other fields should be optional unless required by a specific workflow.
- Optional fields: SKU/code, barcode, category, brand, description, image, unit of measure, variant attributes and preferred supplier.
- Purchasing/cost fields: purchase price, transport cost and other additional costs. Store the inputs and define a consistent landed-cost calculation.
- Sales fields: standard selling price, optional tax treatment, discount constraints and online publication status.
- Support product variants where feasible without making simple single-variant products harder to enter.

## 8.2 Landed cost and margin

- Calculate landed cost from purchase cost plus allocated additional costs. Define allocation rules for costs that apply to multiple products (for example, proportional to quantity or value) before implementing shared-cost allocation.
- Distinguish markup from margin in calculations. The user-facing interface may use a plain-language “target profit” setting, but the system must clearly define whether the percentage means markup or gross margin and show the suggested price before saving.
- Allow a default pricing rule, category-level overrides and product-level overrides.
- Suggested hierarchy: business default → category rule → product override.
- Show cost, selling price and estimated profit only to authorised users.
- Preserve historical transaction prices and cost snapshots so later product edits do not rewrite past sales.

## 8.3 Excel import

- Workflow: upload file → map columns → preview rows → identify errors/duplicates → confirm import → provide a result summary.
- Provide a downloadable template and support common spreadsheet formats selected for MVP.
- Allow mapping for product name, SKU, barcode, category, purchase price, selling price, quantity and other supported fields.
- Validate rows before writing data. Clearly identify records requiring attention and avoid partial, unexplained imports.
- Opening stock imported with products must create auditable stock-opening records rather than bypassing stock history.

## 9. Inventory and Stock Control

- Maintain a stock balance per product and stock location/branch.
- Represent stock changes as traceable movements with quantity, source/destination where relevant, reason, timestamp, actor and linked transaction.
- Stock-in reasons include purchase/receiving, customer return, transfer-in and approved adjustment.
- Stock-out reasons include sale, damage, loss, transfer-out and approved adjustment.
- Provide stock history and current availability by branch.
- Support transfers between branches with linked outgoing and incoming records. Define transfer states and handling for dispatch/receipt discrepancies.
- Provide stock-count mode: select location, scan/search product, show expected quantity, enter counted quantity, review variance and post an adjustment with reason and audit trail.
- Configure minimum stock and reorder level; distinguish warning, critical and out-of-stock states.
- Notify authorised users of low stock through in-app notifications and email where configured.
- Prevent negative stock by default; any exception policy must be an explicit business setting with appropriate permissions and audit records.
- Do not allow sales, returns, transfers or purchase corrections to create duplicate stock movements.

## 10. Sales and Point of Sale

- Provide a fast sales screen with product search and barcode scanning where supported by device hardware.
- Allow quantity changes, line removal, permitted discounts and customer selection.
- Display available stock and selling price according to permissions and business rules.
- Support cash, bank transfer, mobile payment (including configurable local methods such as Telebirr and CBE Birr), card, credit, split payment and other configured methods.
- On completion, create the sale, its line items, payment records, stock movements and receipt as one consistent operation.
- Support receipt printing/download or sharing according to available platform capabilities.
- Preserve sale-time price, discount, tax and cost snapshots for reliable historical reporting.
- Apply role-based discount limits and approval requirements when configured.
- Customer-specific/wholesale pricing is planned for a later release unless explicitly promoted into MVP.

## 11. Credit Management and Payment Reminders

## 11.1 Credit sales

- Within the normal sales workflow, allow payment selection of Credit or Split payment alongside immediate payment methods.
- Record customer where known, total sale amount, amount paid, calculated outstanding balance, optional due date and notes/agreement details.
- Calculate outstanding balance as total sale amount minus payments received.
- Any sale with a balance due must appear in receivables and the customer’s credit history.

## 11.2 Credit purchases and supplier payables

- When recording a purchase/stock receipt, capture supplier where known, purchase amount, amount paid, outstanding balance, optional due date and notes.
- Link the payable to its purchase/receiving transaction. Payments must not create duplicate inventory movements or duplicate purchase costs.
- Show outstanding supplier balances in payables.

## 11.3 Due dates and overdue rules

- Due dates are optional. Offer quick choices such as today, tomorrow, 7 days, 15 days, 30 days and custom date.
- A balance without a due date remains outstanding but is not overdue solely due to elapsed time.
- A balance becomes overdue only when its due date has passed and an amount remains unpaid.
- Changing a due date must reschedule reminders and update overdue state.

## 11.4 Internal reminders

- Generate reminders for approaching due dates, due today and overdue receivables/payables.
- Initial channels: in-app and email; push notifications may be added where supported.
- Reminder timing and notification preferences should be configurable by the business.
- Initial reminders are internal to the owner and authorised staff. Do not automatically message customers or suppliers in MVP.
- A generated reminder is not proof that a customer or supplier was contacted.
- Telegram, SMS, WhatsApp and customer-facing automated reminders are future enhancements.

## 11.5 Dashboard and credit views

- Show permitted summary cards for total receivables, due today, due within 7 days and overdue receivables.
- Show equivalent payable summaries for suppliers.
- Selecting a card opens the corresponding filtered transaction list.
- Provide views for due today, due soon, overdue, outstanding, partially paid and paid history.
- Allow filtering by customer/supplier, branch, transaction date, due date and status, subject to permissions.

## 11.6 Payments and activity history

- Support multiple partial payments against a credit transaction.
- For each payment record amount, date, method, recording user, reference and optional notes.
- Update balance and status automatically. Prevent accidental duplicate payments and define explicit handling for overpayments.
- Allow authorised follow-up activity records such as called, message sent, promise to pay or arrangement discussed.
- Follow-up activities must not change balances or mark transactions paid by themselves.
- Audit due-date changes, payment corrections, cancellations and other material credit operations.

## 11.7 Credit limits, status and integrity

- Support optional customer credit limits with configurable warning, approval or blocking behaviour.
- Use statuses such as outstanding, partially paid, paid, overdue and cancelled/voided.
- Derive status from balance, due date and cancellation state; never mark a transaction paid with a remaining balance.
- Restrict viewing balances, creating credit, recording payments, changing due dates, approving exceptions and cancelling/correcting transactions through granular permissions.
- Keep transaction and payment history auditable; do not silently delete financial history.

## 11.8 Credit MVP acceptance criteria

- A user can record credit sales and credit purchases in their normal workflows.
- Balances are calculated correctly and due dates are optional.
- Overdue classification follows the defined due-date and remaining-balance rules.
- Partial and final payments update balances and statuses correctly without duplication.
- Internal reminders are delivered according to configured schedules and permissions.
- Dashboard summaries and filtered lists show receivables and payables without leaking restricted data.
- Customer/supplier histories show transactions, payments, balances and follow-up records.
- Credit actions do not duplicate inventory movements or purchase costs.

## 12. Customers and Suppliers

- Customer fields may include name, phone, Telegram username, email, address and notes.
- Show customer purchase history, quotations/orders and credit balance subject to permissions.
- Supplier records may include name, contact information, products supplied, purchase history and payable balance.
- Keep CRM workflows lightweight for MVP; avoid requiring extensive contact profiles for a walk-in sale.
- Support customer and supplier records being optional for workflows where the business chooses not to identify the counterparty, while applying stricter requirements where credit tracking needs a named account.

## 13. Ecommerce and Online Catalogue

- Allow a product to be published to the online shop using a simple availability toggle.
- Use the same product catalogue and stock source as physical sales; do not create a separate disconnected inventory catalogue.
- Reflect stock availability online and define whether zero-stock products are hidden or shown as out of stock.
- Provide product detail pages with image, description, price and seller contact/enquiry options.
- Allow customers to submit enquiries and quotation/proforma requests without requiring online payment in MVP.
- Capture customer name, phone, company if applicable, delivery location and notes for a request.
- Provide a simple mobile-friendly storefront and shareable shop/product links.
- Online orders/requests must not reserve or reduce stock until a defined confirmation/fulfilment step is implemented.

## 14. Quotations and Proformas

- Allow a customer request to be reviewed by an authorised owner/manager/salesperson.
- Generate a uniquely numbered quotation/proforma with products, quantities, unit prices, discounts, applicable tax, delivery charges and total.
- Support PDF output and a secure, mobile-friendly share link.
- Allow sharing by email and provide a practical Telegram sharing workflow; other channels may be added later.
- Allow the customer to contact the seller and, where supported, accept or request changes.
- Define quotation validity, status transitions and whether acceptance creates a confirmed order before implementation.
- A proforma must not be treated as a completed sale, payment or stock deduction until converted through an explicit workflow.

## 15. Reports and Dashboards

- Home dashboard: today’s sales, order count, items sold, low-stock alerts, outstanding receivables/payables and relevant branch summary.
- Sales reports: by period, branch, salesperson, payment method, product and category.
- Profit reports: based on sale-time cost snapshots and clearly stated calculation rules.
- Inventory reports: on-hand quantity, stock movements, stock valuation at cost, potential sales value and low-stock items.
- Credit reports: receivables, payables, due and overdue balances, payments and aging where defined.
- Branch comparison: sales, profit, order count and stock metrics, with no unauthorised cross-branch visibility.
- Product/category performance and salesperson performance, permission-controlled.
- Provide filters and export capability for agreed formats. Clearly indicate reporting date range, currency and calculation basis.
- Do not label a branch or salesperson “best” without making the metric and reporting period explicit; present factual rankings only as data views.

## 16. Localisation and Market Requirements

- Support ETB as the initial business currency and format amounts consistently.
- Prepare the interface for English and Amharic, including translated labels, validation messages, notification templates and printable documents.
- Support Ethiopian phone number formats and country code handling.
- Provide Ethiopian calendar support as a product requirement to be designed carefully alongside Gregorian dates used by integrations and storage.
- Allow local payment methods to be configured without assuming that the app itself processes those payments in MVP.
- Design for variable connectivity; full offline-first synchronisation is planned for a later phase unless explicitly scoped into MVP.
- Make tax, VAT and invoice rules configurable and confirm legal requirements with qualified local advice before production compliance claims.

## 17. Subscription, Trial and Data Retention

- New businesses receive a configurable free trial period.
- Notify the business about registration, trial start and approaching expiry using configured channels.
- Platform administrators can configure trial length, subscription plans, tenant status and feature access.
- When a trial expires, apply a clearly communicated restricted or read-only state according to the subscription policy.
- Do not automatically delete tenant data because a trial expires. Define retention, export and eventual deletion policies explicitly.
- Subscription restrictions must not corrupt or silently alter inventory, sales, payment or credit records.

## 18. Technical Architecture and Engineering Constraints

- Web frontend: Next.js with TypeScript.
- Mobile application: Flutter.
- Backend: Python with FastAPI, exposing a documented REST API using OpenAPI.
- Database: PostgreSQL.
- Background jobs/notifications: Redis and a worker process, or an equivalent replaceable mechanism.
- Local development: Docker Compose with documented setup, seed data and repeatable migrations.
- Initial deployment: a modest VPS/container-based environment; design deployment components to be replaceable as scale grows.
- File storage: abstract storage behind an interface. Use local disk or a zero-cost/local development option during testing; keep an S3-compatible provider as a future configuration rather than a testing prerequisite.
- Use database migrations for schema changes. Keep migrations safe, reviewable and non-destructive by default.
- Maintain API contracts and typed client models; avoid duplicating business rules in web and mobile clients.
- Use background processing for scheduled reminders, email delivery and other non-blocking work.
- Provide environment-based configuration and never commit secrets.

## 19. Core Data Entities

- The implementation may refine names and normalisation, but the domain model should account for at least the following concepts:
- Platform: PlatformAdmin, Tenant/Business, SubscriptionPlan, Subscription, FeatureFlag, AuditEvent.
- Access: User, TenantMembership, Role, Permission, BranchMembership/Assignment.
- Operations: Branch, Warehouse/StockLocation, Product, ProductVariant, Category, Supplier, Customer.
- Inventory: StockBalance or derived balance, StockMovement, StockTransfer, StockCount, StockAdjustment.
- Sales: Sale, SaleLine, Payment, PaymentAllocation, Receipt, DiscountApproval.
- Purchasing: Purchase, PurchaseLine, GoodsReceipt, SupplierPayment.
- Credit: Receivable/Payable or equivalent transaction balance model, DueDate, Reminder, FollowUpActivity, CreditLimit.
- Commerce: OnlineStore, PublishedProduct state, CustomerEnquiry, Quotation/Proforma, QuotationLine, Order where scoped.
- System: Notification, FileAsset, ImportJob, ImportRowError, AuditLog.
- Choose a consistent financial ledger/transaction model. Avoid maintaining the same balance independently in several tables without reconciliation rules. Use database constraints and transactions for financial and stock-critical operations.

## 20. Security, Privacy and Reliability

- Enforce tenant isolation on the server and database access paths; never rely solely on frontend filtering.
- Use secure authentication, password/session handling, rate limiting and appropriate account recovery.
- Apply least-privilege access and test permission boundaries for every sensitive operation.
- Audit privileged actions, financial corrections, stock adjustments, due-date changes and administrative support access.
- Protect personal and business data in transit and at rest using appropriate deployment controls.
- Validate uploads and restrict file type/size; protect against malicious files and spreadsheet formula injection in exports.
- Use idempotency or equivalent safeguards for payment, sale and stock posting operations where retries could duplicate effects.
- Back up the database and uploaded assets, and periodically test restoration.
- Use structured logs, error monitoring, health checks and alerting.
- Define data export, retention, account deletion and incident response processes before broad production rollout.

## 21. Testing and Quality Requirements

- Unit tests for pricing, margin/markup, landed cost, credit balances, due-date status and permission logic.
- Integration tests for sale completion, payment allocation, purchase receiving, stock transfers, adjustments and cancellations.
- Tenant-isolation tests proving that one tenant cannot read or modify another tenant’s data.
- Permission tests for owner, manager, salesperson and stock-user capabilities.
- End-to-end tests for onboarding, Excel import, sale, credit payment, reminder and proforma workflows.
- Test duplicate submissions, retries, concurrent sales and partial failure recovery.
- Test timezone/date handling, Gregorian/Ethiopian calendar display decisions, ETB formatting and Amharic text rendering.
- Run migrations against representative existing data and test backup restoration.
- Automated checks should run in CI before merge; release candidates must pass agreed regression and acceptance tests.

## 22. AI Coding Agent and Change Management Rules

- Treat this PRD, approved architecture notes, API contracts and relevant module-level specifications as the authoritative requirements.
- Before coding, inspect the existing implementation and identify affected screens, APIs, models, permissions, jobs, reports, tests and migrations.
- For every change, write a short impact analysis and identify assumptions or unresolved decisions.
- Do not invent product behaviour when the requirements are ambiguous. Ask for clarification or document a proposed decision for approval.
- Make small, focused changes. Avoid unrelated refactoring and do not silently expand scope.
- Add or update automated tests and documentation alongside implementation.
- Never bypass tenant isolation, permission checks, auditability or transaction integrity for convenience.
- Do not directly modify production data or deploy unreviewed code to production.
- Use feature flags for risky or staged capabilities where appropriate.
- Use backward-compatible, non-destructive migrations by default. Explain any data migration and provide a recovery plan.
- Require code review, staging verification and user acceptance testing for material changes.
- Deploy in controlled stages, monitor errors and business metrics, and maintain a rollback or forward-fix plan.
- Keep API and schema changes coordinated across web, mobile and backend clients.
- Update this PRD or linked specifications when an approved requirement changes; record the decision and date.

## 23. Standard Change and Release Workflow

- Requirement raised and clarified.
- Impact analysis completed, including user experience, data, API, permissions, reports, tests and deployment.
- Decision/approval recorded for scope and unresolved trade-offs.
- Implementation plan and acceptance criteria agreed.
- Development on a feature branch with focused commits.
- Automated tests, static checks and code review completed.
- Deploy to staging/test environment.
- Perform regression checks and user acceptance testing.
- Prepare release notes, migration/backup plan and rollback or recovery approach.
- Deploy to production in an appropriate window and avoid unnecessary disruption.
- Monitor logs, health, key workflows and user-reported issues.
- Close the change only after verification and documentation updates.

## 24. MVP Acceptance Gate

- A new owner can register, create a business and first branch, import or add products, and complete a basic sale without specialist assistance.
- A tenant can add branches and users while keeping its data isolated from other tenants.
- Stock balances remain consistent across sales, receipts, transfers, returns and adjustments.
- Authorised users can record credit sales and purchases, track partial payments and see accurate due/overdue states.
- Internal credit reminders and dashboard summaries work without messaging customers automatically.
- A shop owner can publish products online and receive an enquiry or proforma request using the same catalogue.
- A user can generate and share a quotation/proforma without accidentally posting a sale or reducing stock.
- Core reports agree with underlying transactions and respect access permissions.
- Security, tenant isolation, backup/restore, migration and regression checks pass.
- Trial expiry applies the configured access policy without deleting business data.

## 25. Open Decisions to Resolve Before Relevant Implementation

- Exact trial length, plan limits, prices, grace period and expired-account restrictions.
- Tax/VAT, invoice and receipt requirements, including whether and when tax calculations apply.
- Whether stock can go negative and which roles may approve exceptions.
- How shared transport and other purchase costs are allocated across multiple products.
- Whether sale completion requires a named customer for credit, and whether anonymous credit is permitted.
- Overpayment, refund, cancellation, return and reversal policies for sales, purchases and payments.
- Whether quotations can be accepted online and what acceptance does to stock availability.
- Whether stock transfers require dispatch and receipt confirmation in MVP.
- Exact supported Excel formats, import limits and duplicate matching rules.
- Ethiopian calendar interaction model and date storage/display conventions.
- Email delivery provider, Telegram integration approach and notification delivery guarantees.
- Local hosting, data residency, privacy and compliance obligations to confirm before production launch.

## 26. Product Success Measures

- Time from registration to first product and first completed sale.
- Percentage of new businesses completing onboarding and importing products successfully.
- Weekly active businesses and active branches.
- Sales and stock workflows completed successfully without support intervention.
- Credit transactions with recorded due dates and follow-up activity.
- Reminder delivery success and overdue balances reviewed by users.
- Inventory discrepancy frequency and stock adjustment trends.
- Online product publication rate and quotation/enquiry conversion funnel.
- Support requests, error rate, crash rate and data-integrity incidents.
- Trial-to-paid conversion and retention, once subscription billing is enabled.

## Appendix A. Guiding Workflow Examples

### A1. Add a product quickly

- User enters a product name, selling price, quantity and category if known, then saves. Advanced details such as SKU, barcode, cost, supplier, image and description remain optional and can be completed later.

### A2. Complete a credit sale

- Salesperson selects products and quantities, chooses Credit or Split payment, selects/creates a customer where required, records any amount received and optionally chooses a due date. The system posts the sale and stock movements, creates the receivable, displays the balance and schedules internal reminders.

### A3. Receive stock with supplier credit

- Authorised user records the supplier and received items, purchase costs and amount paid. The system updates stock once, records the payable and optional due date, and makes the balance visible to authorised users.

### A4. Publish an item online

- Owner enables online publication for a product. The storefront uses the same catalogue and stock availability. A customer can enquire or request a proforma; no stock is deducted merely because a request is received.

### A5. Reconcile a stock count

- User selects a branch, scans/searches products, enters counted quantities, reviews variances and posts approved adjustments. The system records who counted, when, why and the resulting movements.
