"""Create tenant-scoped chart of accounts and double-entry journal tables.

Revision ID: 6c3f9a1d7e42
Revises: 5d8a2c7f4e91
"""
from alembic import op
import sqlalchemy as sa

revision = "6c3f9a1d7e42"
down_revision = "5d8a2c7f4e91"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("parent_account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "code", name="uq_ledger_account_company_code"),
    )
    op.create_index("ix_ledger_accounts_company_type", "ledger_accounts", ["company_id", "account_type"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("entry_number", sa.String(50), nullable=False),
        sa.Column("entry_date", sa.DateTime(), nullable=False),
        sa.Column("narration", sa.String(500), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("source_id", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "entry_number", name="uq_journal_company_number"),
        sa.UniqueConstraint("company_id", "source_type", "source_id", name="uq_journal_company_source"),
    )
    op.create_index("ix_journal_entries_company_date", "journal_entries", ["company_id", "entry_date"])

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("description", sa.String(250), nullable=False, server_default=""),
        sa.Column("debit", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_journal_lines_account", "journal_lines", ["account_id"])


def downgrade():
    op.drop_index("ix_journal_lines_account", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_company_date", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_ledger_accounts_company_type", table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
