# ERP SaaS Product Blueprint

**Working product name:** New brand to be selected after name, domain, and trademark screening  
**Target market:** India  
**Platforms:** Responsive web + Android/iOS mobile  
**Initial customer wedge:** Wholesale, distribution, and retail businesses  
**Existing product:** Windows desktop GST Billing System remains supported during the cloud transition.

## 1. Product vision

Build an easy-to-use, India-focused business operating system for small and growing businesses. It should combine GST billing, inventory, purchasing, accounting workflows, multi-branch operations, and business visibility in one product.

The product should feel simple to a shop owner while supporting the controls needed by accountants, warehouse teams, sales staff, and multi-location operators.

## 2. Target customers and launch sequence

1. **Pilot segment:** Wholesale and distribution businesses with multiple products, stock locations, suppliers, and repeat customers.
2. **Next segments:** Retailers and small manufacturers.
3. **Later segments:** Service businesses and broader SMB workflows.

The addressable market is India-wide, but the first release should focus on a narrow set of workflows so onboarding, support, and product quality remain manageable.

## 3. User roles

- **Platform operator:** Operates the SaaS platform, subscriptions, support, and tenant lifecycle. Platform access must not imply unrestricted access to customer business data.
- **Tenant owner:** Owns the customer account, subscription, and tenant-level settings.
- **Company administrator:** Manages companies, branches, warehouses, and memberships within the tenant.
- **Accountant:** Handles invoices, purchases, payments, and reports.
- **Sales user:** Creates quotations, invoices, and customer follow-ups within assigned scope.
- **Warehouse user:** Handles stock receipts, adjustments, and transfers.
- **Read-only user:** Views only explicitly permitted information.

## 4. Core product modules

### MVP / first commercial release
- Tenant signup, secure login, guided business onboarding
- Company, branch, warehouse, and staff management
- GST sales invoices, quotations, credit/debit notes
- Customer and supplier ledgers
- Products, units, HSN/SAC, tax configuration
- Purchase / stock-in and warehouse stock transfers
- Receipts, payments, expenses, cash/bank registers
- Essential sales, purchase, stock, receivable, payable, and GST reports
- PDF/print and controlled export
- Import from supported spreadsheet templates
- Subscription plan, billing status, and account settings
- Audit history, backup/restore operations, and support workflow

### Later releases
- Barcode workflows and batch/serial/expiry tracking
- E-invoice and e-way bill integrations where legally applicable
- WhatsApp/email messaging and payment reminders
- Bank statement import and reconciliation
- Advanced accounting and financial statements
- CRM pipeline, purchase approvals, and workflow automation
- AI-assisted business summaries and natural-language reporting
- Offline-tolerant mobile workflows and push notifications
- Integrations/API for external commerce and accounting systems

Regulated GST capabilities must be validated against current Indian rules and tested with a qualified GST practitioner before being marketed as compliant. Integrations must use authorized providers and applicable government interfaces.

## 5. UX principles

- First-run setup should guide the owner through business identity, GST details, financial year, first branch, warehouse, and opening stock.
- Common tasks should be reachable in a few obvious steps.
- Use plain language, clear empty states, sensible defaults, keyboard support, and visible save/error feedback.
- Responsive web layout should work on desktop, tablet, and mobile.
- Mobile should prioritize invoice creation, customer lookup, payment collection, stock lookup, and approvals.
- English first, with localization-ready text and Malayalam/Hindi support planned.
- Do not hide important actions in ambiguous icons; label actions such as Transfer Stock, Record Payment, and Create Invoice.
- Provide import previews and validation before any bulk data is committed.

## 6. Proposed technical architecture

- **Web:** Next.js / React, responsive design system.
- **Mobile:** React Native, sharing API contracts and business terminology with web.
- **Backend:** Python FastAPI, versioned REST API, OpenAPI documentation.
- **Database:** PostgreSQL for hosted SaaS; SQLite remains supported for the existing desktop edition during transition.
- **Data access:** SQLAlchemy with Alembic migrations. Business rules should move behind application services rather than live in UI handlers.
- **Authentication:** Secure password hashing, short-lived access tokens, refresh-token rotation/revocation, MFA option, email verification, rate limiting, and session/device management.
- **Authorization:** Tenant membership + company/branch/warehouse scope, enforced server-side on every request. Never trust tenant or company IDs supplied by the client without checking membership.
- **Files:** Private object storage with tenant-scoped paths, signed access, malware scanning, and retention controls.
- **Operations:** Managed PostgreSQL, secrets manager, TLS, centralized logs/metrics, error monitoring, backups, point-in-time recovery, and tested restore procedures.
- **Payments:** Integrate an India-capable payment gateway after pricing, tax treatment, and subscription lifecycle are finalized.

## 7. Multi-tenancy and data isolation

A tenant represents one customer account/organization on the SaaS platform. A tenant may own multiple companies; each company may contain branches and warehouses. A user may belong to one or more tenants and receive scoped roles.

Every tenant-owned record must carry a tenant boundary directly or through a rigorously enforced parent relationship. All API queries and writes must be tenant-scoped. PostgreSQL row-level security may be added as defense in depth after the application-level model is established and tested.

Important current-repository gaps to resolve before customer data is hosted:
- Current User.username is globally unique and has no tenant membership lifecycle.
- Current Product.sku is globally unique rather than company/tenant-scoped.
- Existing Company is a business entity, not a SaaS tenant.
- Some service functions open their own global SessionLocal; API work needs explicit request-scoped sessions and service transaction boundaries.
- Existing init_db() performs create_all, ad-hoc ALTERs, and creates a known default admin account. Hosted deployments must use reviewed Alembic migrations and a secure tenant-owner bootstrap instead.
- Existing local audit and access patterns are a useful start but are not yet a complete SaaS security boundary.

## 8. Commercial packaging (hypotheses to validate)

| Plan concept | Indicative monthly price | Intended fit |
|---|---:|---|
| Starter | ₹499 | Single-location small business |
| Growth | ₹999 | Growing shop / wholesale operator |
| Business | ₹1,999 | Multiple users and branches |
| Enterprise | Custom | Larger multi-company operations |

These are research hypotheses, not final prices. Validate willingness to pay, support costs, payment gateway fees, storage, messaging, and tax treatment with pilot customers.

Potential packaging limits: users, branches, companies, monthly documents, storage, and premium integrations. Avoid hard limits that make core stock/accounting data unsafe or inaccessible.

## 9. Launch and success measures

Start with 5–10 design-partner businesses. Observe onboarding completion, time to first invoice, weekly active businesses, invoice volume, stock accuracy, support requests, retention, and paid conversion. Expand only after backup/restore, tenant isolation, auditability, and core accounting workflows pass acceptance tests.

## 10. Brand work

Do not settle a brand name until domain availability, pronunciation in Indian languages, relevant trademark classes, and conflicting software/company names have been screened. Keep the repository and internal project name neutral until then.
