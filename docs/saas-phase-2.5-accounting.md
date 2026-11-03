# SaaS Phase 2.5 — Accounting ledger foundation

## Included

- Company-scoped chart of accounts with unique account codes per company.
- Starter Indian small-business chart seeded lazily on first chart request.
- Manual double-entry journal posting with debit/credit equality validation.
- Tenant-scoped Trial Balance and account General Ledger reports.
- Audit event for manual journal posting.
- Automatic, source-linked journals for sales invoices, customer receipts, purchase bills, and supplier payments.
- Reversal journals on eligible sales invoice and purchase bill cancellation.
- Source-level idempotency: one journal per company/source type/source ID.
- Automated API tests for chart isolation, balanced posting, reports, invalid totals, and cross-tenant account rejection.

## API

- `GET /erp/accounting/accounts`
- `POST /erp/accounting/journals`
- `GET /erp/accounting/trial-balance?as_of=YYYY-MM-DD`
- `GET /erp/accounting/ledger/{account_id}?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`
- `GET /erp/accounting/journals?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD&limit=100`
- `GET /erp/accounting/profit-loss?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`
- `GET /erp/accounting/balance-sheet?as_of=YYYY-MM-DD`
- `GET /erp/accounting/cash-flow?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` (cash/bank ledger movement summary)

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

Automatic postings now cover invoice receivables/revenue/output GST, purchase inventory/input GST/payables, and payment settlement against cash/bank. Eligible invoice and purchase cancellations create reversing journals. Sales COGS and inventory valuation are deliberately not posted because the current product model does not yet provide a reliable cost-layer valuation. This phase does not provide period locking, bank reconciliation, financial statements, or a GST-compliant tax determination engine. Manual journal endpoints must not be mistaken for a complete production accounting package.

Before production use, add PostgreSQL concurrency tests, accounting period controls, payment reversal/refund workflows, immutable ledger enforcement at the database/service boundary, inventory cost-layer valuation and COGS, and a qualified Indian accounting/GST review. Validate every posting map and rollback path with endpoint-level automated tests.


## Phase 2.7 — Financial report API additions

- Profit & Loss aggregates posted income and expense journal lines for a required date range.
- Balance Sheet aggregates posted asset, liability and equity balances as of a date, and includes accumulated current earnings in equity.
- Cash & Bank Summary reports movements in the configured Cash (1000) and Bank (1010) ledgers. It is explicitly not a classified statutory cash flow statement.
- Journal Register lists posted journal entries with optional date filters and a bounded result limit.
- All four reports are company/tenant scoped and restricted to owner, admin, manager and accountant roles.
- Automated tests cover financial totals, balance-sheet equality, cash/bank movements, journal register isolation, and invalid date ranges.

### Reporting limitations

Reports reflect only posted journal entries and the current starter chart. Balance Sheet classification and retained/current earnings treatment need review by a qualified Indian accountant before production. Cash & Bank Summary is a ledger movement report, not an indirect cash flow statement. CSV/Excel/PDF exports, financial-year/period locking, journal reversal UI/workflows, statutory financial statements and GST compliance reports remain future work.
