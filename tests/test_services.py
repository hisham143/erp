from decimal import Decimal
from sqlalchemy import select
from app.db import init_db, SessionLocal, Customer, Product, BusinessSettings, Invoice, InvoiceItem
from app.services import create_invoice

def test_intra_state_invoice_and_stock_deduction():
    init_db()
    with SessionLocal.begin() as s:
        settings = s.scalar(select(BusinessSettings).limit(1))
        settings.state_code = "32"
        customer = Customer(name="Pytest customer", state_code="32")
        product = Product(sku="PYTEST-SKU", name="Pytest product", hsn_sac="1234",
                          unit="Nos", selling_price=Decimal("100.00"), purchase_price=Decimal("50.00"),
                          gst_rate=Decimal("18.00"), stock_qty=Decimal("10.000"), reorder_level=Decimal("1.000"))
        s.add_all([customer, product])
        s.flush()
        cid, pid = customer.id, product.id
    inv_id, number = create_invoice(cid, [{"product_id": pid, "quantity": "2", "discount_amount": "0"}], "pytest")
    with SessionLocal() as s:
        inv = s.get(Invoice, inv_id)
        product = s.get(Product, pid)
        assert inv.invoice_number == number
        assert Decimal(inv.taxable_total) == Decimal("200.00")
        assert Decimal(inv.cgst_total) == Decimal("18.00")
        assert Decimal(inv.sgst_total) == Decimal("18.00")
        assert Decimal(inv.grand_total) == Decimal("236.00")
        assert Decimal(product.stock_qty) == Decimal("8.000")
