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
- app/saas/api.py provides GET /health/live and GET /health/ready.
- requirements.txt includes FastAPI, Uvicorn, and Psycopg 3.
- tests/test_saas_config.py checks SQLite and PostgreSQL engine options.
- docs/saas-product-blueprint.md captures the product and architecture direction.

## Important safety boundaries

- Do not point ERP_DATABASE_URL at a production database until tenant migrations, authentication, authorization, backups, and restore testing are complete.
- The current API intentionally has no login or business-data endpoints. Do not expose it publicly as a usable SaaS product yet.
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
