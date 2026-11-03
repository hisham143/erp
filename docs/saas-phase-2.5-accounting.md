# SaaS Phase 2.5 — Accounting ledger foundation

## Included

- Company-scoped chart of accounts with unique account codes per company.
- Starter Indian small-business chart seeded lazily on first chart request.
- Manual double-entry journal posting with debit/credit equality validation.
- Tenant-scoped Trial Balance and account General Ledger reports.
- Audit event for manual journal posting.
- Automated API tests for chart isolation, balanced posting, reports, invalid totals, and cross-tenant account rejection.

## API

- `GET /erp/accounting/accounts`
- `POST /erp/accounting/journals`
- `GET /erp/accounting/trial-balance?as_of=YYYY-MM-DD`
- `GET /erp/accounting/ledger/{account_id}?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`

Manual journal body example:

```json
{
  "entry_date": "2026-11-01",
  "narration": "Owner capital introduced",
  "lines": [
    {"account_id": 1, "description": "Cash received", "debit": "1000.00", "credit": "0"},
    {"account_id": 2, "description": "Capital introduced", "debit": "0", "credit": "1000.00"}
  ]
}
```

Account IDs are company-specific; clients must read the chart endpoint rather than assume IDs.

## Starter chart codes

| Code | Account | Type |
|---|---|---|
| 1000 | Cash | Asset |
| 1010 | Bank | Asset |
| 1100 | Accounts Receivable | Asset |
| 1200–1220 | Input CGST / SGST / IGST | Asset |
| 1300 | Inventory | Asset |
| 2000 | Accounts Payable | Liability |
| 2100–2120 | Output CGST / SGST / IGST | Liability |
| 3000 | Owner's Capital | Equity |
| 3100 | Retained Earnings | Equity |
| 4000 | Sales Revenue | Income |
| 4100 | Other Income | Income |
| 5000 | Cost of Goods Sold | Expense |
| 5100 | Purchases | Expense |
| 5200 | Rent Expense | Expense |
| 5300 | Salary Expense | Expense |
| 5400 | Other Expenses | Expense |

## Important accounting boundaries

This phase does **not** yet automatically post Sales invoices, customer receipts, Purchase bills, supplier payments, GST liabilities/ITC, stock valuation, or cost of goods sold. It does not provide period locking, reversal vouchers, bank reconciliation, financial statements, or a GST-compliant tax determination engine. Manual journal endpoints must not be mistaken for a complete production accounting package.

Before production use, add PostgreSQL concurrency tests, accounting period controls, immutable reversal workflows, source-to-journal posting idempotency, and a qualified Indian accounting/GST review. Do not connect existing transaction endpoints to automatic journals until each posting map and rollback path has dedicated automated tests.
