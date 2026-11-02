# Aster ERP Reference Review and Product UI Inventory

## Purpose and source boundary

The uploaded Aster ERP dashboard image and `aster_erp_full_interactive_demo.html` are visual and navigation references. They are not production requirements, a tested codebase, or proof that the displayed actions work. The HTML is a browser-only demo with fictional seed data persisted to localStorage. Its own labels explicitly describe GST, POS, payroll, banking, manufacturing, and other areas as demo or simulated.

Adopt the reference's visual language:
- Deep navy sidebar with a clear active state and grouped navigation
- Light neutral workspace, white cards, restrained purple primary actions
- Compact KPI cards, readable tables, clear status labels
- Consistent page heading, search/filter toolbar, primary action placement
- Responsive collapse to mobile navigation and stacked cards
- Consistent form fields, dialogs, empty states, loading states, and confirmations

Do not copy the demo's fake numbers, fixed January 2025 dates, placeholder alerts, localStorage data model, or claims of functionality. Production screens must read from tenant-scoped APIs and persisted database records.

## Reference modules captured

The HTML navigation contains 22 page entries including Dashboard and the following business areas:

1. CRM & Customers
2. Sales & Invoices
3. Purchase & Suppliers
4. Inventory & Warehouses
5. Point of Sale
6. Manufacturing
7. Quality Control
8. Accounting & Ledger
9. GST & Compliance
10. Banking
11. Fixed Assets
12. HR & Employees
13. Payroll
14. Projects & Tasks
15. Logistics
16. Service Desk
17. Documents
18. Reports & Analytics
19. Users & Roles
20. Company Settings
21. SaaS Subscription

The reference also demonstrates invoice creation, product catalogue, customer directory, employee list, sales report, recent transactions, quick actions, and plan usage. These should be treated as screen concepts, not complete workflows.

## Functional gaps visible in the reference prototype

- Browser localStorage is the persistence layer; there is no authenticated API or tenant isolation.
- Demo users/roles are static examples; role-based authorization is not enforced.
- Several buttons only show alerts or prototype messages (POS cart, payroll preview, report refresh, date filter, manufacturing, logistics, banking).
- GST values are illustrative; no verified GST calculations, return preparation, IRP/IRN, e-way bill, or GSTN integration is performed.
- Dashboard KPIs, charts, reports, and recent transactions are hardcoded or derived from fixed sample data, not live transactions.
- Invoice form captures a subtotal and GST rate but not a complete invoice line/tax model; HSN/SAC, discounts, round-off, tax jurisdiction, place-of-supply validation, payment terms, and stock posting are incomplete.
- Product and stock demo data has no warehouse-level stock ledger, stock adjustment approval, or transfer workflow.
- The table View action is a generic alert rather than a record detail/edit workflow.
- CSV export is browser-side and does not provide server-side authorization, audit logging, large-export handling, or import validation.
- Company settings are local demo fields without validated GSTIN/state mapping or tenant/company lifecycle.
- Subscription usage is a static illustrative meter; there is no plan entitlement enforcement or payment lifecycle.
- No real file upload, private document storage, malware scanning, or access-controlled downloads.
- No audit history, idempotency, concurrency controls, or automated end-to-end tests are included in the HTML prototype.

## Product module coverage and phased delivery

### Commercial MVP (first paid release)
- SaaS registration, login, verification, recovery, tenant onboarding
- Tenant, company, branch, warehouse, user, role, and access management
- CRM/customer and supplier masters
- Product catalogue, units, HSN/SAC, GST configuration, warehouse stock
- Quotations, sales orders, GST invoices, credit/debit notes, receipts
- Purchase orders, goods receipt, supplier bills, supplier payments
- Stock adjustments, inter-warehouse transfers, stock ledger
- Basic cash/bank book, expenses, receivables/payables
- GST-oriented sales/purchase summaries and reconciliation exports
- Core dashboards, operational reports, PDF/print, controlled CSV/XLSX import/export
- Subscription plans, usage entitlements, audit trail, support and data export

### Planned modules after core ERP stability
- POS with barcode scanner, returns, shifts, cash drawer, payment reconciliation
- Manufacturing with BOM, work orders, material issue/receipt, costing and traceability
- Quality inspection plans, test results, non-conformance and corrective action
- Full accounting: chart of accounts, journals, trial balance, P&L, balance sheet
- Banking feeds/import and reconciliation
- Fixed asset register, depreciation schedules, disposal
- HR, attendance, leave, payroll, payslips and statutory calculations
- Projects, tasks, timesheets and project costing
- Logistics, dispatch, shipment tracking and delivery proof
- Service desk, warranties, returns and service history
- Document management with versioning, retention, access policy and audit
- Advanced analytics, integrations, automation and AI assistance

The modules are not to be marked complete merely because a navigation item or screen exists. Each must pass its own workflow and permission tests before release.

## UI acceptance rules

Every production module screen must have:
- Loading, empty, populated, error, and permission-denied states
- Search/filter/sort/pagination appropriate to its data volume
- Explicit create/view/edit/archive actions and confirmation for destructive actions
- Field-level validation and accessible keyboard/focus behavior
- Responsive desktop/tablet/mobile layout
- Tenant/company/branch/warehouse scope visible where relevant
- Currency in INR, Indian number formatting, Asia/Kolkata dates/time
- Audit metadata for financially or operationally significant mutations
- No fake metrics, hardcoded customer data, or dead-end buttons

## Automated quality gates

A module is eligible to progress only when all relevant gates pass:

1. Static checks: compile, lint/type checks where applicable, migration drift check.
2. Unit tests: calculations, validators, permissions, state transitions, edge cases.
3. API integration tests: successful, invalid, unauthenticated, unauthorized, duplicate, and concurrent requests.
4. Tenant isolation tests: cross-tenant read/write attempts must fail.
5. Company/branch/warehouse scope tests: cross-scope access must fail.
6. Database tests: constraints, transaction rollback, uniqueness, migration upgrade/downgrade on disposable databases.
7. UI end-to-end tests: critical journeys on desktop and mobile viewport sizes; assert no console errors and no dead controls.
8. Regression suite: desktop SQLite workflows remain intact.
9. Security checks: dependency audit, secret handling, rate limiting, session revocation, file access checks.
10. Release evidence: reproducible command output and test report attached to the change.

Do not claim "fully tested" from a passing unit-test count alone. Manual exploratory testing may supplement automated testing but cannot replace it. If a required test environment or provider sandbox is unavailable, mark that integration as blocked/not verified rather than passing it.

## Immediate implementation order

1. Correct and freeze the UI design system and navigation information architecture.
2. Finish tenant onboarding and business setup (business profile, GST identity, first company, branch, warehouse, financial year).
3. Build authenticated web shell and role-aware navigation against the SaaS API.
4. Deliver the core wholesale workflows in vertical slices: customer/product -> purchase/receipt -> stock -> invoice -> payment -> reports.
5. Add automated UI end-to-end tests and tenant/scope regression tests before broadening module scope.


## Current delivery evidence

The first tenant onboarding vertical slice now has:
- Tenant-scoped business profile persistence, separate from legacy desktop Company records
- Authenticated GET and owner/admin-only PUT endpoints
- GSTIN format and GST state-code consistency validation (not live GSTN verification)
- Automated tests for save/read-back, cross-tenant isolation, invalid GSTIN, state mismatch, and unregistered setup
- Additive Alembic migration `f3b7d9a2c641`

Not yet implemented: creation/linkage of actual tenant-owned Company, Branch, and Warehouse records; GSTIN verification; email verification; full responsive web onboarding UI. Do not represent these as complete.


## Web UI delivery — initial shell

The Aster-inspired web entry UI is now implemented at `web/index.html`, `web/app.css`, and `web/app.js`, served from FastAPI at `/`. It includes tenant registration/sign-in, workspace code display, business-profile onboarding, GST/state inputs, branch/warehouse naming, saved-profile confirmation, edit, and sign-out. Layout breakpoints are covered by a Playwright browser test at mobile and tablet widths.

This is intentionally not a fake dashboard. No fabricated KPI values or nonfunctional ERP module links are shown. The UI must not be described as the full dashboard or finished ERP until the actual business modules and live data services are implemented.
