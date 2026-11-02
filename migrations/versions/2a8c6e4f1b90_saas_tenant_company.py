"""Link SaaS tenants to their operational ERP company hierarchy.

Revision ID: 2a8c6e4f1b90
Revises: f3b7d9a2c641
"""
from alembic import op
import sqlalchemy as sa

revision = "2a8c6e4f1b90"
down_revision = "f3b7d9a2c641"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saas_tenant_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("saas_tenants.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_saas_tenant_companies_tenant"),
        sa.UniqueConstraint("company_id", name="uq_saas_tenant_companies_company"),
    )


def downgrade():
    op.drop_table("saas_tenant_companies")
