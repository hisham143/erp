"""Create isolated SaaS tenants, identities, memberships, and refresh sessions.

Revision ID: e6a4c9b1d732
Revises: c91d7e4a62b8
"""
from alembic import op
import sqlalchemy as sa


revision = "e6a4c9b1d732"
down_revision = "d4e8a1c7b930"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saas_tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_saas_tenants_slug", "saas_tenants", ["slug"], unique=True)

    op.create_table(
        "saas_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(length=180), nullable=False),
        sa.Column("password_hash", sa.String(length=160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_saas_identities_email", "saas_identities", ["email"], unique=True)

    op.create_table(
        "saas_tenant_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("saas_tenants.id"), nullable=False),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("saas_identities.id"), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="owner"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "identity_id", name="uq_saas_tenant_identity"),
    )

    op.create_table(
        "saas_refresh_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("saas_tenants.id"), nullable=False),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("saas_identities.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_saas_refresh_sessions_token_hash",
        "saas_refresh_sessions",
        ["token_hash"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_saas_refresh_sessions_token_hash", table_name="saas_refresh_sessions")
    op.drop_table("saas_refresh_sessions")
    op.drop_table("saas_tenant_memberships")
    op.drop_index("ix_saas_identities_email", table_name="saas_identities")
    op.drop_table("saas_identities")
    op.drop_index("ix_saas_tenants_slug", table_name="saas_tenants")
    op.drop_table("saas_tenants")
