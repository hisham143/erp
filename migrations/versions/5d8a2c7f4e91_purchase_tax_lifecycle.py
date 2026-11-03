"""Add purchase tax breakdown and lifecycle state.

Revision ID: 5d8a2c7f4e91
Revises: 2a8c6e4f1b90
"""
from alembic import op
import sqlalchemy as sa

revision = "5d8a2c7f4e91"
down_revision = "2a8c6e4f1b90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("purchases", sa.Column("cgst_total", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchases", sa.Column("sgst_total", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchases", sa.Column("igst_total", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchases", sa.Column("status", sa.String(20), nullable=False, server_default="received"))
    op.add_column("purchase_items", sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchase_items", sa.Column("cgst_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchase_items", sa.Column("sgst_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchase_items", sa.Column("igst_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("purchase_items", "igst_amount")
    op.drop_column("purchase_items", "sgst_amount")
    op.drop_column("purchase_items", "cgst_amount")
    op.drop_column("purchase_items", "discount_amount")
    op.drop_column("purchases", "status")
    op.drop_column("purchases", "igst_total")
    op.drop_column("purchases", "sgst_total")
    op.drop_column("purchases", "cgst_total")
