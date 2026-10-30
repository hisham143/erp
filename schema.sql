-- Reference schema overview. SQLAlchemy models in app/db.py are the executable schema.
CREATE TABLE business_settings (
  id INTEGER PRIMARY KEY, legal_name TEXT NOT NULL, gstin TEXT, state_code TEXT NOT NULL,
  address TEXT, phone TEXT, invoice_prefix TEXT NOT NULL, logo_path TEXT NOT NULL DEFAULT '',
  next_invoice_number INTEGER NOT NULL
);
CREATE TABLE users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL
);
CREATE TABLE customers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, gstin TEXT, state_code TEXT NOT NULL,
  address TEXT, phone TEXT, email TEXT, active BOOLEAN NOT NULL
);
CREATE TABLE products (
  id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, hsn_sac TEXT,
  unit TEXT, selling_price NUMERIC NOT NULL, purchase_price NUMERIC NOT NULL,
  gst_rate NUMERIC NOT NULL, stock_qty NUMERIC NOT NULL, reorder_level NUMERIC NOT NULL, active BOOLEAN NOT NULL
);
CREATE TABLE invoices (
  id INTEGER PRIMARY KEY, invoice_number TEXT UNIQUE NOT NULL, invoice_date DATETIME NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id), seller_state_code TEXT NOT NULL,
  place_of_supply_state_code TEXT NOT NULL, is_interstate BOOLEAN NOT NULL,
  taxable_total NUMERIC NOT NULL, cgst_total NUMERIC NOT NULL, sgst_total NUMERIC NOT NULL,
  igst_total NUMERIC NOT NULL, grand_total NUMERIC NOT NULL, amount_paid NUMERIC NOT NULL,
  status TEXT NOT NULL, created_by TEXT NOT NULL
);
CREATE TABLE invoice_items (
  id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  product_id INTEGER REFERENCES products(id), sku_snapshot TEXT, description_snapshot TEXT NOT NULL,
  hsn_sac_snapshot TEXT, unit_snapshot TEXT, quantity NUMERIC NOT NULL, unit_price NUMERIC NOT NULL,
  discount_amount NUMERIC NOT NULL, gst_rate_snapshot NUMERIC NOT NULL, taxable_value NUMERIC NOT NULL,
  cgst_amount NUMERIC NOT NULL, sgst_amount NUMERIC NOT NULL, igst_amount NUMERIC NOT NULL, line_total NUMERIC NOT NULL
);
CREATE TABLE payments (
  id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  amount NUMERIC NOT NULL, method TEXT NOT NULL, reference TEXT, paid_at DATETIME NOT NULL, recorded_by TEXT NOT NULL
);
CREATE TABLE stock_movements (
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  quantity_delta NUMERIC NOT NULL, reason TEXT NOT NULL, reference TEXT, created_at DATETIME NOT NULL, created_by TEXT NOT NULL
);
CREATE TABLE audit_logs (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL, action TEXT NOT NULL, entity_type TEXT,
  entity_id TEXT, details TEXT, created_at DATETIME NOT NULL
);

CREATE TABLE suppliers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, gstin TEXT, state_code TEXT NOT NULL,
  address TEXT, phone TEXT, active BOOLEAN NOT NULL
);
CREATE TABLE purchases (
  id INTEGER PRIMARY KEY, purchase_number TEXT UNIQUE NOT NULL, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  supplier_invoice_number TEXT, purchase_date DATETIME NOT NULL, taxable_total NUMERIC NOT NULL,
  tax_total NUMERIC NOT NULL, grand_total NUMERIC NOT NULL, amount_paid NUMERIC NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL
);
CREATE TABLE purchase_items (
  id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id),
  product_id INTEGER NOT NULL REFERENCES products(id), sku_snapshot TEXT, description_snapshot TEXT NOT NULL,
  hsn_sac_snapshot TEXT, quantity NUMERIC NOT NULL, unit_cost NUMERIC NOT NULL,
  gst_rate_snapshot NUMERIC NOT NULL, taxable_value NUMERIC NOT NULL, tax_amount NUMERIC NOT NULL, line_total NUMERIC NOT NULL
);
CREATE TABLE supplier_payments (
  id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id), amount NUMERIC NOT NULL,
  method TEXT NOT NULL, reference TEXT, paid_at DATETIME NOT NULL, recorded_by TEXT NOT NULL
);
