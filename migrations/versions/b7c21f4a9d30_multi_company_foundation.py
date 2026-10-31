"""Add multi-company, branch, warehouse and access foundation.

Revision ID: b7c21f4a9d30
Revises: a4be178c5cad
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c21f4a9d30"
down_revision: Union[str, Sequence[str], None] = "a4be178c5cad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("legal_name", sa.String(length=180), nullable=False),
        sa.Column("gstin", sa.String(length=15), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("email", sa.String(length=180), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_branch_company_code"),
    )
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "code", name="uq_warehouse_branch_code"),
    )
    op.create_table(
        "user_company_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "company_id", name="uq_user_company_access"),
    )
    op.create_table(
        "branch_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "branch_id", name="uq_user_branch_access"),
    )
    op.create_table(
        "product_stock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("reorder_level", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "warehouse_id", name="uq_product_stock_warehouse"),
    )


def downgrade() -> None:
    op.drop_table("product_stock")
    op.drop_table("branch_access")
    op.drop_table("user_company_access")
    op.drop_table("warehouses")
    op.drop_table("branches")
    op.drop_table("companies")
