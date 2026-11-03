# SaaS Phase 1 — Foundation Work

## Objective

Prepare the existing desktop ERP codebase for a separate hosted API without disrupting the current Windows desktop workflow or local SQLite data.

## Phase 1 work sequence

1. **Runtime configuration (started):** preserve local SQLite as the default and allow an explicit ERP_DATABASE_URL for hosted PostgreSQL.
2. **API shell (started):** introduce FastAPI liveness and database-readiness endpoints. No business data endpoints are exposed yet.
3. **Tenant identity model:** design SaaS tenants separately from the existing Company business entity; introduce tenant memberships and scoped roles through reviewed migrations.
4. **Authentication:** implement email-based identity, password reset, verification, session/token lifecycle, rate limits, and optional MFA.
5. **Authorization:** enforce tenant, company, branch, and warehouse scope on every request; add cross-tenant negative tests.
6. **Service boundary:** refactor business operations to accept an explicit request-scoped session and authorized context; remove hidden global session ownership from API call paths.
7. **Data portability:** build validated export/import and rehearsal tooling before any desktop-to-cloud customer migration.
8. **Operations readiness:** secrets, TLS, logs, monitoring, backups, restore drills, deployment pipeline, and incident procedures.

## Current implementation in this branch

- app/saas/config.py resolves ERP_DATABASE_URL, defaulting to the existing gst_billing.db SQLite file.
- app/db.py creates its SQLAlchemy engine using dialect-aware options. Desktop installs continue to use SQLite unless the environment variable is explicitly set.
- app/saas/api.py provides health endpoints plus development-only tenant registration, login, refresh, and authenticated profile routes.
- SaaS identity models are separate from the legacy desktop users table.
- Alembic migration `e6a4c9b1d732` adds tenant, identity, membership, and refresh-session tables after the stock-transfer migration.
- `tests/test_saas_config.py` checks SQLite and PostgreSQL engine options; `tests/test_saas_auth.py` covers registration, login, token rotation, and protected profile access.
- docs/saas-product-blueprint.md captures the product and architecture direction.

## Important safety boundaries

- Do not point ERP_DATABASE_URL at a production database until tenant migrations, authentication, authorization, backups, and restore testing are complete.
- Authentication is an early development foundation only. It is not a complete production identity service; do not expose it publicly as a usable SaaS product yet.
- Do not call init_db() from the hosted API. Production schema changes must use reviewed Alembic migrations.
- Do not use the desktop default admin credentials for hosted tenants.
- Do not migrate or delete local customer data during Phase 1. Existing SQLite database and backups remain untouched.
- Never assume the existing company_id filters alone provide SaaS tenant isolation.
- All migrations must be additive, reviewed, tested against a disposable copy, and preceded by a verified backup for local database work.

## Phase 1 exit criteria

- A clean development environment can start the API and pass liveness/readiness checks.
- PostgreSQL connectivity is verified in a separate disposable development database.
- Tenant/user/company membership schema is reviewed and migrated safely.
- Authentication and authorization tests prove that one tenant cannot read or mutate another tenant's data.
- Desktop regression tests continue to pass using the default SQLite configuration.
- A data migration rehearsal and database restore drill are documented and successful.

## Local API smoke test

After installing requirements, with the desktop app closed and the existing SQLite database still the default:

    python -m pip install -r requirements.txt
    uvicorn app.saas.api:app --host 127.0.0.1 --port 8000

In another PowerShell window:

    Invoke-RestMethod http://127.0.0.1:8000/health/live
    Invoke-RestMethod http://127.0.0.1:8000/health/ready

Stop the API with Ctrl+C. These endpoints verify only process/database connectivity; they do not mean tenant authentication or production readiness is complete.


## Tenant registration and login foundation (implemented; development only)

The SaaS identity model is intentionally separate from the desktop `users` table:
- `saas_tenants`: SaaS customer workspace
- `saas_identities`: normalized unique email identity
- `saas_tenant_memberships`: role and active membership in a tenant
- `saas_refresh_sessions`: hashed, expiring, revocable refresh tokens

API routes:
- `POST /auth/register`: creates a tenant and its first owner in one transaction
- `POST /auth/login`: authenticates an email/password against an active tenant membership
- `POST /auth/refresh`: rotates the opaque refresh token; the old token cannot be reused
- `GET /auth/me`: returns the tenant membership associated with the bearer access token

Access tokens expire after 15 minutes. Refresh tokens are random opaque values stored only as SHA-256 hashes and expire after 30 days. Passwords use the application's PBKDF2-HMAC-SHA256 password hashing helper. The signing secret is never generated or defaulted by the application.

### Local development setup

After taking a fresh verified backup, pull the branch and install dependencies. Inspect the current Alembic revision before applying the additive SaaS migration:

    git pull --ff-only origin feature/erp-foundation
    python -m pip install -r requirements.txt
    python -m compileall app tests
    python -m alembic current

If the current revision is the expected prior revision, take/verify a fresh backup and then run:

    python -m alembic upgrade head
    python -m alembic check
    python -m pytest -q

Generate a strong local-only signing secret and set it in the same PowerShell window used to start Uvicorn:

    python -c "import secrets; print(secrets.token_urlsafe(48))"

Copy the generated value locally (do not share it), then:

    $env:ERP_AUTH_SECRET = "PASTE_YOUR_LOCAL_SECRET_HERE"
    uvicorn app.saas.api:app --host 127.0.0.1 --port 8000

Use the interactive API documentation at `http://127.0.0.1:8000/docs` to exercise registration, login, refresh, and `/auth/me`.

This is a development foundation, not a public-launch-ready identity service. Email verification, password reset, MFA, login/registration rate limiting, abuse controls, security event monitoring, tenant lifecycle administration, and production secret management remain required before public exposure. Do not deploy this API publicly or point it at production data.


## Reference-driven UI and quality gate

The uploaded Aster ERP image and interactive HTML are reference-only. The detailed review, module inventory, prototype limitations, UI acceptance rules, phased scope, and automated quality gates are recorded in `docs/aster-erp-reference-audit.md`.

Do not promote a module from prototype to complete until its automated unit, API integration, authorization/scope, database, UI end-to-end, and desktop regression tests pass. Tests must include negative cases (unauthenticated, unauthorized, cross-tenant, cross-company/branch/warehouse) and validation/rollback cases. Manual testing can supplement but never substitute for automated gates. External integrations without a sandbox must remain explicitly unverified.

### Current authentication implementation status

The initial registration/login routes were exercised in the user's local development environment, including a successful tenant registration response. This is not evidence of complete security or production readiness. Email verification, password recovery, rate limiting, MFA, session management UI, security monitoring, and a production secret-management setup remain open requirements.


## Tenant business onboarding API (first vertical slice)

The tenant-scoped `saas_business_profiles` table stores onboarding details separately from the legacy desktop `companies` table. This avoids silently mixing SaaS tenant identity with existing desktop company records while the cloud data model is still being designed.

Implemented endpoints:
- `GET /onboarding/business`: retrieve the authenticated tenant's saved profile; returns 404 until one is saved.
- `PUT /onboarding/business`: create or update the authenticated tenant's profile; only tenant owner/admin roles may save.

The profile currently captures trade/legal name, GSTIN, two-digit state code, registration type, financial-year start month, address, phone, first branch name, and first warehouse name. GSTIN checks currently validate format and state-code consistency only; they do not verify GST registration with GSTN. The endpoint saves onboarding metadata; it does not yet create records in the legacy `companies`, `branches`, or `warehouses` tables. That integration requires the tenant/company relational design and explicit data-isolation tests.

Migration `f3b7d9a2c641` adds the profile table. Tests cover tenant isolation, persisted read-back, malformed GSTIN, state mismatch, and unregistered businesses.


## ERP Cloud web entry and onboarding UI (development preview)

A responsive static frontend is served by the same FastAPI application:
- `/`: sign-in and create-workspace interface
- `/web-assets/app.css`: responsive Aster-inspired design system
- `/web-assets/app.js`: API-connected form behavior
- Authenticated onboarding form saves/loads the tenant business profile through the SaaS API.
- The workspace slug is displayed for later sign-in.
- Sign-out revokes the current refresh session through `POST /auth/logout`.

The browser keeps the short-lived access token in memory and the rotating refresh token in an HttpOnly, SameSite=Lax cookie scoped to `/auth`. On reload, the frontend calls `/auth/refresh`, rotates the refresh cookie, and restores the signed-in tenant without asking for credentials again. Logout revokes the refresh session and clears the cookie. Set `ERP_COOKIE_SECURE=1` behind HTTPS in production; local HTTP development defaults this flag off. SameSite is a defense-in-depth measure, not a complete CSRF review; before public launch, add explicit Origin/CSRF protections, rate limiting, secure secret management, email verification, and session management controls.

The frontend currently provides authentication, business profile setup, and a saved-profile confirmation only. It does not yet create operational Company/Branch/Warehouse records, show live business KPIs, or expose incomplete ERP modules. It is a development preview, not a production-ready public login service.

Automated API tests also check that the web page and static assets are served and that logout revokes the refresh token. Browser-based Playwright coverage remains a separate required gate before calling the responsive UI fully verified.


### Browser test command

Install the optional browser test dependency and Chromium:

    python -m pip install -r requirements-ui-test.txt
    python -m playwright install chromium

Run the full suite:

    python -m pytest -q

The Playwright test starts an isolated temporary SQLite-backed API process and checks registration, business setup save/read, automatic HttpOnly-cookie session restoration after reload and explicit sign-out/login, and responsive layout behavior at mobile (390px) and tablet (768px) widths. It does not connect to or modify the user's desktop database.


## Operational ERP provisioning from SaaS onboarding

Migration `2a8c6e4f1b90` adds `saas_tenant_companies`, a one-to-one workspace-to-operational-company mapping with references to its first branch and warehouse.

When an authorized tenant owner/admin saves Business Setup, the API now creates (in the same database transaction):
- One operational `Company` populated from the business profile.
- One `Branch` using the supplied first branch name and code `MAIN`.
- One `Warehouse` using the supplied first warehouse name and code `MAIN`.
- One `BusinessSettings` row for the company.
- One `SaaSTenantCompany` mapping linking the tenant to these records.

Repeated profile saves update the linked master records rather than creating duplicates. `GET /onboarding/business` and `GET /onboarding/erp-setup` return the linked operational identifiers. Tenant isolation is enforced by resolving the mapping only through the authenticated tenant ID.

This is an initial provisioning bridge, not yet the complete cloud ERP service boundary. SaaS identities are intentionally not copied into the legacy desktop `users` table, and legacy `UserCompanyAccess` / `BranchAccess` are not created from this endpoint. Operational transaction APIs must continue to enforce tenant/company/branch/warehouse authorization before any cloud business data is exposed.

### Migration and verification gate

The new migration is additive and does not rewrite or delete existing company, branch, warehouse, customer, invoice, stock, or backup data. Before applying it to a local database, close the desktop application and API, make a new timestamped backup without overwriting any prior backup, verify that the backup can be opened, and inspect the current Alembic revision. Then apply the migration and run the complete automated suite, Alembic check, and browser E2E test. Never run this migration against production data before a separate disposable PostgreSQL rehearsal and restore drill.


## Phase 1.5 — tenant authorization and ERP master read boundary

Implemented on `feature/erp-foundation`:
- `GET /workspace/members`: owner/admin-only member listing, scoped to the authenticated tenant.
- `PATCH /workspace/members/{identity_id}/role`: owner-only role update for an existing active non-owner member. The API does not allow changing the owner role through this endpoint.
- `GET /erp/context`: resolves the authenticated tenant's mapped company, branch, and warehouse and rejects inactive or inconsistent context.
- `GET /erp/customers`, `GET /erp/products`, and `GET /erp/suppliers`: read-only master-data endpoints filtered by the tenant's mapped operational company.
- Automated tests seed two separate tenant companies and verify cross-tenant master records are not returned; role tests verify owner/admin permissions and tenant membership scoping.

Supported membership roles currently recognized by the role-management endpoint: owner, admin, manager, accountant, sales, and staff. Member invitations, identity provisioning, branch/warehouse-level grants, transactional APIs, write APIs, and audit/event logging are not part of this slice yet. Do not treat this as production-ready authorization until those controls and the broader security review are complete.


## Phase 2.1 — Sales invoice API (first transaction slice)

Implemented on `feature/erp-foundation`:
- `POST /erp/sales/invoices`: creates an invoice for an active customer and active products belonging to the authenticated tenant's mapped company.
- `GET /erp/sales/invoices`: lists invoices for the authenticated tenant's mapped company only.
- `GET /erp/sales/invoices/{invoice_id}`: retrieves one invoice only when it belongs to the authenticated tenant's company.
- Invoice creation is restricted to owner, admin, manager, accountant, and sales roles. All authenticated workspace members can read company invoices.
- Invoice lines snapshot SKU, product name, HSN/SAC, unit, quantity, price, discount, and GST rate so later product-master edits do not rewrite historical line descriptions.
- GST is calculated per line using decimal arithmetic and two-decimal half-up rounding. Intra-state tax is split equally into CGST/SGST (with any rounding remainder assigned to SGST); inter-state tax is IGST.
- Invoice numbers are assigned after the database row receives its ID, avoiding a shared mutable counter in this initial implementation.
- Automated tests cover GST totals, invoice persistence, cross-tenant invoice/customer isolation, invalid discount rollback, unauthenticated access, and role denial.

Current boundaries:
- This is the first API transaction slice, not a complete legally compliant invoicing workflow. It does not yet implement invoice PDF generation, e-invoice/IRN, e-way bills, credit/debit notes, numbering-series configuration, payment recording, stock deduction, accounting ledger posting, cancellation/void rules, or audit events.
- Invoice creation currently records the invoice and its tax snapshots only; it intentionally does not mutate stock or accounting balances. Those must be implemented as coordinated transaction services with dedicated tests before operational use.
- The existing legacy `invoices.invoice_number` column is globally unique. The generated identifier includes company ID and invoice ID to avoid collisions across companies; configurable per-branch financial-year numbering remains future work.
- Do not treat this endpoint as production-ready tax compliance or enable public customer use until tax-rule review, accounting/stock integration, auditability, and deployment security gates are complete.


## Phase 2.2 — Sales payment recording and invoice balances

Implemented on `feature/erp-foundation`:
- `POST /erp/sales/invoices/{invoice_id}/payments`: records a customer payment against an invoice belonging to the authenticated tenant's company.
- Payment entry is limited to owner, admin, manager, accountant, and sales roles. Invoice reads remain tenant/company scoped.
- The endpoint locks the invoice row where supported by the database, validates the outstanding balance, and records the Payment row plus invoice balance/status update in one database transaction.
- Partial payments set invoice status to `partially_paid`; full settlement sets it to `paid`. Newly issued invoices retain `issued` until a payment is recorded.
- Invoice responses now include `balance_due` and payment history (amount, method, reference, timestamp).
- A repeated non-empty payment reference on the same invoice is rejected to reduce accidental duplicate entry. This is an application-level guard, not a substitute for a provider webhook idempotency key.
- Automated tests cover partial-to-full settlement, overpayment rejection, duplicate reference rejection, persistence, unauthenticated access, role denial, and cross-tenant invoice isolation.

Boundaries and operational cautions:
- No database migration was required; the existing Payment table and Invoice.amount_paid/status fields are reused.
- This slice does not yet integrate payment gateway webhooks, refunds, reversals, bank reconciliation, accounting ledger postings, receipt PDFs, or payment deletion/void workflows.
- Do not treat client-submitted payment details as proof of bank/gateway settlement. Gateway integrations must verify signed provider callbacks and implement durable idempotency before production use.
- Do not manually edit invoice balances or delete payment rows; future reversal workflows must create auditable compensating entries.


## Phase 2.3 — Sales invoice stock control and cancellation

Implemented on `feature/erp-foundation`:

- Invoice creation aggregates quantities by product and deducts from the workspace's linked warehouse in the same database transaction as invoice creation.
- If no `product_stock` row exists yet, its opening quantity is initialized from the legacy `Product.stock_qty` value. This is a one-time compatibility bridge for the current single-warehouse SaaS mapping.
- Insufficient stock returns HTTP 409; the invoice, stock row/movement, and quantity changes are rolled back together.
- Each deduction writes a `StockMovement` row (`sales_invoice`) and an `AuditLog` entry.
- `POST /erp/sales/invoices/{invoice_id}/cancel` restores quantities, writes reversal stock movements and an audit entry, and marks the invoice cancelled atomically.
- Cancellation is restricted to owner/admin/manager/accountant. Invoices with any recorded payment cannot be cancelled; a refund/payment-reversal workflow must be implemented first. Repeated cancellation is rejected.
- Legacy `Product.stock_qty` is synchronized with the linked warehouse quantity for desktop compatibility. This aggregate field is not a correct multi-warehouse total; remove this compatibility coupling when the full warehouse stock UI/service is migrated.

### Concurrency and production limitations

The API applies SQLAlchemy row-level `FOR UPDATE` locks to product and warehouse stock rows. PostgreSQL enforces these locks; SQLite ignores them, so the local SQLite test suite does not prove concurrent oversell protection. Before production launch, add PostgreSQL integration tests and a concurrency test using atomic conditional stock updates or an appropriately isolated transaction strategy. No schema migration is required for this slice because the existing `product_stock`, `stock_movements`, and `audit_logs` tables are reused.

Automated tests cover stock deduction, insufficient-stock rollback, cancellation restoration/idempotency, paid-invoice cancellation rejection, tenant isolation, and role restrictions. Run the complete test suite locally before treating this phase as verified.
