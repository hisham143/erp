"""Authorization helpers for selecting a user's ERP working context.

A context is a company + branch + warehouse combination explicitly assigned
to the user. The UI must carry these IDs into every data operation.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Company, Branch, Warehouse, UserCompanyAccess, BranchAccess


def get_accessible_contexts(session: Session, user_id: int) -> list[dict]:
    """Return active company/branch/warehouse contexts assigned to a user.

    No implicit access is granted: missing company or branch assignments
    produce no contexts. This prevents a newly-created user from inheriting
    access simply because a company or warehouse exists.
    """
    company_rows = session.execute(
        select(Company, UserCompanyAccess.is_default)
        .join(UserCompanyAccess, UserCompanyAccess.company_id == Company.id)
        .where(
            UserCompanyAccess.user_id == user_id,
            Company.active.is_(True),
        )
        .order_by(UserCompanyAccess.is_default.desc(), Company.name)
    ).all()

    contexts: list[dict] = []
    for company, is_default in company_rows:
        branch_rows = session.execute(
            select(Branch)
            .join(BranchAccess, BranchAccess.branch_id == Branch.id)
            .where(
                BranchAccess.user_id == user_id,
                Branch.company_id == company.id,
                Branch.active.is_(True),
            )
            .order_by(Branch.name)
        ).scalars().all()

        for branch in branch_rows:
            warehouses = session.scalars(
                select(Warehouse)
                .where(
                    Warehouse.company_id == company.id,
                    Warehouse.branch_id == branch.id,
                    Warehouse.active.is_(True),
                )
                .order_by(Warehouse.name)
            ).all()
            for warehouse in warehouses:
                contexts.append({
                    "company_id": company.id,
                    "company_name": company.name,
                    "branch_id": branch.id,
                    "branch_name": branch.name,
                    "warehouse_id": warehouse.id,
                    "warehouse_name": warehouse.name,
                    "is_default_company": bool(is_default),
                })
    return contexts


def validate_user_context(
    session: Session,
    user_id: int,
    company_id: int,
    branch_id: int,
    warehouse_id: int,
) -> dict:
    """Validate that the requested active context is assigned to the user."""
    context = session.execute(
        select(Company, Branch, Warehouse)
        .join(UserCompanyAccess, UserCompanyAccess.company_id == Company.id)
        .join(BranchAccess, BranchAccess.branch_id == Branch.id)
        .join(
            Warehouse,
            (Warehouse.branch_id == Branch.id)
            & (Warehouse.company_id == Company.id),
        )
        .where(
            UserCompanyAccess.user_id == user_id,
            BranchAccess.user_id == user_id,
            Company.id == company_id,
            Branch.id == branch_id,
            Warehouse.id == warehouse_id,
            Company.active.is_(True),
            Branch.active.is_(True),
            Warehouse.active.is_(True),
        )
    ).first()
    if not context:
        raise PermissionError("You do not have access to the selected company, branch, or warehouse.")
    company, branch, warehouse = context
    return {
        "company_id": company.id,
        "company_name": company.name,
        "branch_id": branch.id,
        "branch_name": branch.name,
        "warehouse_id": warehouse.id,
        "warehouse_name": warehouse.name,
    }
