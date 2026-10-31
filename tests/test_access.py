from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest

from app.db import (
    Base, User, Company, Branch, Warehouse,
    UserCompanyAccess, BranchAccess, hash_password,
)
from app.access import get_accessible_contexts, validate_user_context


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="access-test", password_hash=hash_password("test"))
        company = Company(name="Test Company")
        db.add_all([user, company])
        db.flush()
        branch = Branch(company_id=company.id, name="Main", code="MAIN")
        db.add(branch)
        db.flush()
        warehouse = Warehouse(
            company_id=company.id,
            branch_id=branch.id,
            name="Main Warehouse",
            code="MAIN",
        )
        db.add(warehouse)
        db.flush()
        db.add_all([
            UserCompanyAccess(user_id=user.id, company_id=company.id, is_default=True),
            BranchAccess(user_id=user.id, branch_id=branch.id),
        ])
        db.commit()
        yield db, user.id, company.id, branch.id, warehouse.id
    engine.dispose()


def test_user_gets_only_assigned_active_context(session):
    db, user_id, company_id, branch_id, warehouse_id = session
    contexts = get_accessible_contexts(db, user_id)
    assert len(contexts) == 1
    assert contexts[0]["company_id"] == company_id
    assert contexts[0]["branch_id"] == branch_id
    assert contexts[0]["warehouse_id"] == warehouse_id
    assert contexts[0]["is_default_company"] is True


def test_unassigned_company_is_not_listed(session):
    db, user_id, company_id, branch_id, warehouse_id = session
    other_company = Company(name="Other Company")
    db.add(other_company)
    db.flush()
    other_branch = Branch(
        company_id=other_company.id, name="Other Branch", code="OTHER"
    )
    db.add(other_branch)
    db.flush()
    db.add(Warehouse(
        company_id=other_company.id,
        branch_id=other_branch.id,
        name="Other Warehouse",
        code="OTHER",
    ))
    db.commit()

    contexts = get_accessible_contexts(db, user_id)
    assert {item["company_id"] for item in contexts} == {company_id}


def test_unassigned_context_is_rejected(session):
    db, user_id, company_id, branch_id, warehouse_id = session
    with pytest.raises(PermissionError):
        validate_user_context(
            db, user_id, company_id + 999, branch_id, warehouse_id
        )


def test_assigned_context_validates(session):
    db, user_id, company_id, branch_id, warehouse_id = session
    result = validate_user_context(
        db, user_id, company_id, branch_id, warehouse_id
    )
    assert result["company_id"] == company_id
    assert result["branch_id"] == branch_id
    assert result["warehouse_id"] == warehouse_id
