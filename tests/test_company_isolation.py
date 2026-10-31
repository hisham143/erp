from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest

from app.db import Base, Company, Branch, Warehouse, Customer, Product, Supplier
from app.services import (
    _company_context,
    _company_customer,
    _company_product,
    _company_supplier,
)


@pytest.fixture
def company_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company_a = Company(name="Company A")
        company_b = Company(name="Company B")
        session.add_all([company_a, company_b])
        session.flush()

        branch_a = Branch(company_id=company_a.id, name="Branch A", code="A")
        branch_b = Branch(company_id=company_b.id, name="Branch B", code="B")
        session.add_all([branch_a, branch_b])
        session.flush()

        warehouse_a = Warehouse(
            company_id=company_a.id,
            branch_id=branch_a.id,
            name="Warehouse A",
            code="A",
        )
        warehouse_b = Warehouse(
            company_id=company_b.id,
            branch_id=branch_b.id,
            name="Warehouse B",
            code="B",
        )
        customer_a = Customer(company_id=company_a.id, name="Customer A")
        customer_b = Customer(company_id=company_b.id, name="Customer B")
        product_a = Product(company_id=company_a.id, sku="SKU-A", name="Product A")
        product_b = Product(company_id=company_b.id, sku="SKU-B", name="Product B")
        supplier_a = Supplier(company_id=company_a.id, name="Supplier A")
        supplier_b = Supplier(company_id=company_b.id, name="Supplier B")
        session.add_all([
            warehouse_a, warehouse_b,
            customer_a, customer_b,
            product_a, product_b,
            supplier_a, supplier_b,
        ])
        session.flush()

        yield {
            "session": session,
            "company_a": company_a,
            "company_b": company_b,
            "branch_a": branch_a,
            "branch_b": branch_b,
            "warehouse_a": warehouse_a,
            "warehouse_b": warehouse_b,
            "customer_a": customer_a,
            "customer_b": customer_b,
            "product_a": product_a,
            "product_b": product_b,
            "supplier_a": supplier_a,
            "supplier_b": supplier_b,
        }
    engine.dispose()


def test_company_context_rejects_branch_from_another_company(company_session):
    data = company_session
    with pytest.raises(ValueError, match="branch does not belong"):
        _company_context(
            data["session"],
            data["company_a"].id,
            data["branch_b"].id,
        )


def test_company_context_rejects_warehouse_from_another_company(company_session):
    data = company_session
    with pytest.raises(ValueError, match="warehouse does not belong"):
        _company_context(
            data["session"],
            data["company_a"].id,
            data["branch_a"].id,
            data["warehouse_b"].id,
        )


def test_customer_cannot_be_used_across_companies(company_session):
    data = company_session
    assert _company_customer(
        data["session"], data["customer_a"].id, data["company_a"].id
    ).name == "Customer A"
    with pytest.raises(ValueError, match="unavailable in this company"):
        _company_customer(
            data["session"], data["customer_b"].id, data["company_a"].id
        )


def test_product_cannot_be_used_across_companies(company_session):
    data = company_session
    assert _company_product(
        data["session"], data["product_a"].id, data["company_a"].id
    ).name == "Product A"
    with pytest.raises(ValueError, match="unavailable in this company"):
        _company_product(
            data["session"], data["product_b"].id, data["company_a"].id
        )


def test_supplier_cannot_be_used_across_companies(company_session):
    data = company_session
    assert _company_supplier(
        data["session"], data["supplier_a"].id, data["company_a"].id
    ).name == "Supplier A"
    with pytest.raises(ValueError, match="unavailable in this company"):
        _company_supplier(
            data["session"], data["supplier_b"].id, data["company_a"].id
        )
