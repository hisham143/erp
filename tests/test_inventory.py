from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, Company, Branch, Warehouse, Product, ProductStock
from app.services import _stock_row


def test_legacy_stock_is_moved_to_default_warehouse_only():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            company = Company(name="Inventory test")
            session.add(company)
            session.flush()
            branch = Branch(company_id=company.id, name="Main", code="MAIN")
            session.add(branch)
            session.flush()
            default_warehouse = Warehouse(
                company_id=company.id, branch_id=branch.id,
                name="Main Warehouse", code="MAIN",
            )
            second_warehouse = Warehouse(
                company_id=company.id, branch_id=branch.id,
                name="Secondary Warehouse", code="SECONDARY",
            )
            session.add_all([default_warehouse, second_warehouse])
            session.flush()
            product = Product(
                company_id=company.id, sku="INV-LEGACY-1",
                name="Legacy stock product", stock_qty=Decimal("12.000"),
                reorder_level=Decimal("2.000"),
            )
            session.add(product)
            session.flush()

            secondary_stock = _stock_row(
                session, product, second_warehouse.id, company.id
            )
            assert Decimal(secondary_stock.quantity) == Decimal("0.000")

            default_stock = _stock_row(
                session, product, default_warehouse.id, company.id
            )
            assert Decimal(default_stock.quantity) == Decimal("12.000")

            # Re-reading a warehouse returns its own saved balance.
            default_stock.quantity = Decimal("9.000")
            session.flush()
            reloaded = _stock_row(
                session, product, default_warehouse.id, company.id
            )
            assert Decimal(reloaded.quantity) == Decimal("9.000")

            rows = session.scalars(
                select(ProductStock).where(ProductStock.product_id == product.id)
            ).all()
            assert len(rows) == 2
    finally:
        engine.dispose()
