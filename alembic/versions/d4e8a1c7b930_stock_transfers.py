"""Add stock transfer header and item tables.

Revision ID: d4e8a1c7b930
Revises: c91d7e4a62b8
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa


revision = "d4e8a1c7b930"
down_revision = "c91d7e4a62b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("from_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("to_warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("transfer_number", sa.String(length=40), nullable=False, unique=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=80), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "stock_transfer_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("stock_transfers.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
    )


def downgrade():
    op.drop_table("stock_transfer_items")
    op.drop_table("stock_transfers")
