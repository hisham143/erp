from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services as services_module
from app.db import (
    Base, User, Company, Branch, Warehouse, UserCompanyAccess, BranchAccess,
    Product, ProductStock, StockTransfer, StockTransferItem, StockMovement,
    AuditLog, hash_password,
)
from app.services import transfer_stock


@pytest.fixture
def inventory_context(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(services_module, "SessionLocal", sessions)
    with sessions.begin() as session:
        user = User(username="transfer-test", password_hash=hash_password("test"))
        company = Company(name="Transfer Test Co")
        session.add_all([user, company])
        session.flush()
        branch = Branch(company_id=company.id, name="Main", code="MAIN")
        session.add(branch)
        session.flush()
        source = Warehouse(
            company_id=company.id, branch_id=branch.id,
            name="Source", code="SRC",
        )
        destination = Warehouse(
            company_id=company.id, branch_id=branch.id,
            name="Destination", code="DST",
        )
        session.add_all([source, destination])
        session.flush()
        session.add_all([
            UserCompanyAccess(user_id=user.id, company_id=company.id, is_default=True),
            BranchAccess(user_id=user.id, branch_id=branch.id),
        ])
        product = Product(
            company_id=company.id, sku="TRANSFER-1", name="Transfer Product",
            stock_qty=Decimal("0"), reorder_level=Decimal("0"),
        )
        session.add(product)
        session.flush()
        source_stock = ProductStock(
            company_id=company.id, product_id=product.id,
            warehouse_id=source.id, quantity=Decimal("15.000"),
        )
        destination_stock = ProductStock(
            company_id=company.id, product_id=product.id,
            warehouse_id=destination.id, quantity=Decimal("2.000"),
        )
        session.add_all([source_stock, destination_stock])
        ids = (user.id, company.id, branch.id, source.id, destination.id, product.id)
    yield sessions, ids
    engine.dispose()


def test_stock_transfer_updates_both_warehouses_and_history(inventory_context):
    sessions, (user_id, company_id, branch_id, source_id, destination_id, product_id) = inventory_context

    transfer_id, transfer_number = transfer_stock(
        [{"product_id": product_id, "quantity": "4.500"}],
        destination_id,
        "Replenish destination",
        "transfer-test",
        user_id=user_id,
        company_id=company_id,
        branch_id=branch_id,
        warehouse_id=source_id,
    )

    with sessions() as session:
        source = session.scalar(select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.warehouse_id == source_id,
        ))
        destination = session.scalar(select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.warehouse_id == destination_id,
        ))
        header = session.get(StockTransfer, transfer_id)
        items = session.scalars(select(StockTransferItem).where(
            StockTransferItem.transfer_id == transfer_id
        )).all()
        movements = session.scalars(select(StockMovement).where(
            StockMovement.reference == transfer_number
        )).all()
        audit = session.scalar(select(AuditLog).where(
            AuditLog.entity_type == "stock_transfer",
            AuditLog.entity_id == str(transfer_id),
        ))
        assert Decimal(source.quantity) == Decimal("10.500")
        assert Decimal(destination.quantity) == Decimal("6.500")
        assert header.transfer_number == transfer_number
        assert len(items) == 1
        assert len(movements) == 2
        assert {movement.reason for movement in movements} == {"transfer_out", "transfer_in"}
        assert audit is not None


def test_stock_transfer_rejects_insufficient_stock_without_changes(inventory_context):
    sessions, (user_id, company_id, branch_id, source_id, destination_id, product_id) = inventory_context

    with pytest.raises(ValueError, match="Insufficient stock"):
        transfer_stock(
            [{"product_id": product_id, "quantity": "99"}],
            destination_id,
            user_id=user_id,
            company_id=company_id,
            branch_id=branch_id,
            warehouse_id=source_id,
        )

    with sessions() as session:
        source = session.scalar(select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.warehouse_id == source_id,
        ))
        destination = session.scalar(select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.warehouse_id == destination_id,
        ))
        assert Decimal(source.quantity) == Decimal("15.000")
        assert Decimal(destination.quantity) == Decimal("2.000")
        assert session.scalar(select(StockTransfer.id)) is None


def test_stock_transfer_rejects_same_warehouse(inventory_context):
    _sessions, (user_id, company_id, branch_id, source_id, _destination_id, product_id) = inventory_context
    with pytest.raises(ValueError, match="different"):
        transfer_stock(
            [{"product_id": product_id, "quantity": "1"}],
            source_id,
            user_id=user_id,
            company_id=company_id,
            branch_id=branch_id,
            warehouse_id=source_id,
        )
