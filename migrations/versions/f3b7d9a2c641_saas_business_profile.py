"""Add tenant-scoped business onboarding profile.

Revision ID: f3b7d9a2c641
Revises: e6a4c9b1d732
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b7d9a2c641"
down_revision = "e6a4c9b1d732"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saas_business_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("saas_tenants.id"), nullable=False),
        sa.Column("trade_name", sa.String(180), nullable=False),
        sa.Column("legal_name", sa.String(180), nullable=False, server_default=""),
        sa.Column("gstin", sa.String(15), nullable=False, server_default=""),
        sa.Column("state_code", sa.String(2), nullable=False),
        sa.Column("gst_registration_type", sa.String(30), nullable=False, server_default="regular"),
        sa.Column("financial_year_start_month", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("phone", sa.String(30), nullable=False, server_default=""),
        sa.Column("first_branch_name", sa.String(180), nullable=False, server_default="Main Branch"),
        sa.Column("first_warehouse_name", sa.String(180), nullable=False, server_default="Main Warehouse"),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_saas_business_profile_tenant"),
    )


def downgrade():
    op.drop_table("saas_business_profiles")
