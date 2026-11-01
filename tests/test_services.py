from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
import app.services as services_module
from app.db import (
    User, Company, Branch, Warehouse, UserCompanyAccess, BranchAccess,
    Customer, Product, BusinessSettings, Invoice, ProductStock,
)
from app.services import create_invoice


def test_intra_state_invoice_and_stock_deduction(monkeypatch):
    # Service tests must never write into the developer's real billing database.
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessions = sessionmaker(bind=test_engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_sessions)
    monkeypatch.setattr(services_module, "SessionLocal", test_sessions)
    db_module.init_db()

    with test_sessions.begin() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        company = Company(id=1, name="Test Company", state_code="32")
        session.add(company)
        session.flush()
        branch = Branch(id=1, company_id=company.id, name="Main", code="MAIN")
        session.add(branch)
        session.flush()
        warehouse = Warehouse(
            id=1, company_id=company.id, branch_id=branch.id,
            name="Main Warehouse", code="MAIN",
        )
        session.add(warehouse)
        session.flush()
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

    with test_sessions() as session:
        invoice = session.get(Invoice, invoice_id)
        product = session.get(Product, product_id)
        assert invoice.invoice_number == number
        assert Decimal(invoice.taxable_total) == Decimal("200.00")
        assert Decimal(invoice.cgst_total) == Decimal("18.00")
        assert Decimal(invoice.sgst_total) == Decimal("18.00")
        assert Decimal(invoice.grand_total) == Decimal("236.00")
        assert Decimal(product.stock_qty) == Decimal("10.000")
        stock = session.scalar(select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.warehouse_id == 1,
            ProductStock.company_id == 1,
        ))
        assert Decimal(stock.quantity) == Decimal("8.000")
    test_engine.dispose()
