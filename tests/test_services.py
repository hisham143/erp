from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.db import (
    init_db,
    SessionLocal,
    User,
    UserCompanyAccess,
    BranchAccess,
    Customer,
    Product,
    BusinessSettings,
    Invoice,
)
from app.services import create_invoice


def test_intra_state_invoice_and_stock_deduction():
    init_db()
    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        settings = session.scalar(
            select(BusinessSettings).where(BusinessSettings.company_id == 1).limit(1)
        )
        settings.state_code = "32"

        # Ensure the seeded admin has explicit access to the migrated
        # default company and its primary branch.
        if not session.scalar(
            select(UserCompanyAccess.id).where(
                UserCompanyAccess.user_id == user.id,
                UserCompanyAccess.company_id == 1,
            )
        ):
            session.add(
                UserCompanyAccess(
                    user_id=user.id,
                    company_id=1,
                    is_default=True,
                )
            )
        if not session.scalar(
            select(BranchAccess.id).where(
                BranchAccess.user_id == user.id,
                BranchAccess.branch_id == 1,
            )
        ):
            session.add(BranchAccess(user_id=user.id, branch_id=1))

        customer = Customer(
            company_id=1,
            name="Pytest customer",
            state_code="32",
        )
        product = Product(
            company_id=1,
            sku=f"PYTEST-{uuid4().hex[:12].upper()}",
            name="Pytest product",
            hsn_sac="1234",
            unit="Nos",
            selling_price=Decimal("100.00"),
            purchase_price=Decimal("50.00"),
            gst_rate=Decimal("18.00"),
            stock_qty=Decimal("10.000"),
            reorder_level=Decimal("1.000"),
        )
        session.add_all([customer, product])
        session.flush()
        customer_id, product_id, user_id = customer.id, product.id, user.id

    invoice_id, number = create_invoice(
        customer_id,
        [{"product_id": product_id, "quantity": "2", "discount_amount": "0"}],
        "pytest",
        user_id=user_id,
        company_id=1,
        branch_id=1,
        warehouse_id=1,
    )

    with SessionLocal() as session:
        invoice = session.get(Invoice, invoice_id)
        product = session.get(Product, product_id)
        assert invoice.invoice_number == number
        assert Decimal(invoice.taxable_total) == Decimal("200.00")
        assert Decimal(invoice.cgst_total) == Decimal("18.00")
        assert Decimal(invoice.sgst_total) == Decimal("18.00")
        assert Decimal(invoice.grand_total) == Decimal("236.00")
        assert Decimal(product.stock_qty) == Decimal("8.000")
