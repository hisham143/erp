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

The browser keeps access and refresh tokens in memory only; reloading the page requires signing in again. This avoids putting bearer or refresh tokens in localStorage, but a production web deployment should move to secure HttpOnly, Secure, SameSite cookies with CSRF protections and a reviewed session architecture.

The frontend currently provides authentication, business profile setup, and a saved-profile confirmation only. It does not yet create operational Company/Branch/Warehouse records, show live business KPIs, or expose incomplete ERP modules. It is a development preview, not a production-ready public login service.

Automated API tests also check that the web page and static assets are served and that logout revokes the refresh token. Browser-based Playwright coverage remains a separate required gate before calling the responsive UI fully verified.
