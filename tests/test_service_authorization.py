import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import (
    Base, User, Company, Branch, Warehouse,
    UserCompanyAccess, BranchAccess, hash_password,
)
from app.services import _authorize_user_context


@pytest.fixture
def auth_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="auth-user", password_hash=hash_password("test"))
        company = Company(name="Authorized Co")
        other_company = Company(name="Unassigned Co")
        session.add_all([user, company, other_company])
        session.flush()
        branch = Branch(company_id=company.id, name="Main", code="MAIN")
        other_branch = Branch(company_id=other_company.id, name="Other", code="OTHER")
        session.add_all([branch, other_branch])
        session.flush()
        warehouse = Warehouse(
            company_id=company.id, branch_id=branch.id,
            name="Main Warehouse", code="MAIN",
        )
        other_warehouse = Warehouse(
            company_id=other_company.id, branch_id=other_branch.id,
            name="Other Warehouse", code="OTHER",
        )
        session.add_all([warehouse, other_warehouse])
        session.flush()
        session.add_all([
            UserCompanyAccess(user_id=user.id, company_id=company.id, is_default=True),
            BranchAccess(user_id=user.id, branch_id=branch.id),
        ])
        session.commit()
        yield {
            "session": session, "user": user, "company": company,
            "branch": branch, "warehouse": warehouse,
            "other_company": other_company, "other_branch": other_branch,
            "other_warehouse": other_warehouse,
        }
    engine.dispose()


def test_authorized_user_context_is_accepted(auth_context):
    data = auth_context
    result = _authorize_user_context(
        data["session"], data["user"].id, data["company"].id,
        data["branch"].id, data["warehouse"].id,
    )
    assert result["company_id"] == data["company"].id


def test_missing_user_is_rejected(auth_context):
    data = auth_context
    with pytest.raises(PermissionError, match="signed-in user"):
        _authorize_user_context(
            data["session"], None, data["company"].id,
            data["branch"].id, data["warehouse"].id,
        )


def test_unassigned_company_is_rejected(auth_context):
    data = auth_context
    with pytest.raises(PermissionError, match="do not have access"):
        _authorize_user_context(
            data["session"], data["user"].id, data["other_company"].id,
            data["other_branch"].id, data["other_warehouse"].id,
        )


def test_inactive_user_is_rejected(auth_context):
    data = auth_context
    data["user"].active = False
    data["session"].flush()
    with pytest.raises(PermissionError, match="inactive"):
        _authorize_user_context(
            data["session"], data["user"].id, data["company"].id,
            data["branch"].id, data["warehouse"].id,
        )
