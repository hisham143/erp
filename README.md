# GST Billing System — Windows Desktop MVP

A starter desktop billing application for an Indian wholesale business, built with Python, PySide6, SQLite, SQLAlchemy, and ReportLab.

## Included in this MVP
- Local SQLite database created automatically on first run
- Login screen and role-aware users (admin / staff / viewer)
- Customer and product creation
- GST-aware invoice creation (intra-state CGST+SGST; interstate IGST)
- Invoice register and PDF invoice generation
- Business logo upload and print-safe INR currency formatting on invoice PDFs
- Stock movements and stock deduction when an invoice is issued
- Payment recording and outstanding balance summary
- Sales report summary
- A4 invoice PDF and narrow 58mm/80mm thermal receipt PDF layouts (print manually at actual size from a PDF viewer)
- Supplier bills with multiple product lines, per-line GST entry, stock movements and supplier payment tracking

## Printing note
Thermal receipts are generated as narrow PDF files. This starter does not yet send raw ESC/POS commands directly to a thermal printer. Test the PDF with the client’s actual printer, paper width, margins and scaling settings.

## Important GST note
This is a software starter, not tax/legal advice or a certified GST compliance product. Before client production use, have an Indian GST practitioner validate tax rates, place-of-supply rules, invoice particulars, credit/debit notes, HSN/SAC requirements, e-invoicing/e-way bill applicability, rounding, and reporting against the client's exact business. The sample rate field is configurable per product. Do not assume the sample logic covers every transaction type.

## Setup (Windows PowerShell)
1. Install Python 3.11+.
2. Extract this folder.
3. Open PowerShell in this folder:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   python main.py
   ```
4. Default first-run login:
   - Username: `admin`
   - Password: `ChangeMe123!`
5. Change the default password immediately from the Users tab before entering real business data.

## SaaS API foundation (development only)

The repository is beginning a separate cloud API alongside the existing Windows desktop application.

Install the expanded dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the local API and open the ERP Cloud web interface at `http://127.0.0.1:8000/`:

```powershell
uvicorn app.saas.api:app --host 127.0.0.1 --port 8000
```

The root URL serves the development sign-in and business-onboarding UI. API documentation remains at `http://127.0.0.1:8000/docs`. The UI currently covers tenant registration, sign-in, and tenant business-profile onboarding; it is not yet the full ERP dashboard or a production-ready public login service.

For real-browser automated UI tests, install the optional test dependency and browser:

```powershell
python -m pip install -r requirements-ui-test.txt
python -m playwright install chromium
python -m pytest -q
```

Run the local API:

```powershell
uvicorn app.saas.api:app --host 127.0.0.1 --port 8000
```

Check process and database readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

The desktop app continues to use the existing local SQLite database by default. Cloud development can set ERP_DATABASE_URL to a PostgreSQL URL using the Psycopg 3 driver, for example:

```powershell
$env:ERP_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
```

Do not use a production database URL yet. The API currently exposes health endpoints only; tenant authentication, authorization, SaaS migrations, backups, and production deployment gates are still under development. See docs/saas-product-blueprint.md and docs/saas-phase-1.md.

## Database
- Database file: `gst_billing.db` in the application folder.
- Schema is defined in `app/db.py` and created on first launch.
- Back up the database only after closing the app, or implement SQLite online backup for live production usage.
- Keep a second copy of backups on a separate drive.

## Suggested implementation stages
1. **Stage 1 — Foundation:** database, authentication, company settings, customers and products.
2. **Stage 2 — Wholesale billing:** invoice creation, basic GST split, stock movement, invoice register and A4 PDF.
3. **Stage 3 — Stock-in:** supplier bills with multiple products, per-line GST, automatic stock updates, and partial/full supplier payments.
4. **Stage 4 — Payments & reports:** payments, outstanding balances, sales totals.
5. **Stage 5 — Production readiness:** real printer validation, returns/credit notes, audit review, automated backups, migrations, GST practitioner validation, packaging and acceptance testing.

## Packaging
After testing:
```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name GSTBilling main.py
```
For a real client delivery, also define a safe writable data directory, installer/updater, database backup policy, logging, and versioned schema migrations. Do not ship client data inside the executable.
