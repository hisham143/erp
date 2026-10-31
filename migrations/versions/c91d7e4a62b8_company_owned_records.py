"""Add company ownership and operational scope to existing ERP records.

Revision ID: c91d7e4a62b8
Revises: b7c21f4a9d30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c91d7e4a62b8"
down_revision: Union[str, Sequence[str], None] = "b7c21f4a9d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Create a default company using the existing business settings, preserving
    # the current installation as one company.
    company_count = bind.execute(sa.text("SELECT COUNT(*) FROM companies")).scalar_one()
    if company_count == 0:
        settings = bind.execute(sa.text(
            "SELECT legal_name, gstin, state_code, address, phone "
            "FROM business_settings ORDER BY id LIMIT 1"
        )).mappings().first()
        legal_name = (settings["legal_name"] if settings else "") or "Default Company"
        result = bind.execute(sa.text(
            "INSERT INTO companies (name, legal_name, gstin, state_code, address, phone, email, active, created_at) "
            "VALUES (:name, :legal_name, :gstin, :state_code, :address, :phone, '', 1, CURRENT_TIMESTAMP)"
        ), {
            "name": legal_name,
            "legal_name": legal_name,
            "gstin": (settings["gstin"] if settings else "") or "",
            "state_code": (settings["state_code"] if settings else "32") or "32",
            "address": (settings["address"] if settings else "") or "",
            "phone": (settings["phone"] if settings else "") or "",
        })
        company_id = result.lastrowid
    else:
        company_id = bind.execute(sa.text("SELECT id FROM companies ORDER BY id LIMIT 1")).scalar_one()

    branch_id = bind.execute(sa.text(
        "SELECT id FROM branches WHERE company_id = :company_id ORDER BY id LIMIT 1"
    ), {"company_id": company_id}).scalar()
    if branch_id is None:
        branch_id = bind.execute(sa.text(
            "INSERT INTO branches (company_id, name, code, address, phone, active) "
            "VALUES (:company_id, 'Main Branch', 'MAIN', '', '', 1)"
        ), {"company_id": company_id}).lastrowid

    warehouse_id = bind.execute(sa.text(
        "SELECT id FROM warehouses WHERE branch_id = :branch_id ORDER BY id LIMIT 1"
    ), {"branch_id": branch_id}).scalar()
    if warehouse_id is None:
        warehouse_id = bind.execute(sa.text(
            "INSERT INTO warehouses (company_id, branch_id, name, code, address, active) "
            "VALUES (:company_id, :branch_id, 'Main Warehouse', 'MAIN', '', 1)"
        ), {"company_id": company_id, "branch_id": branch_id}).lastrowid

    company_only = [
        "business_settings", "customers", "products", "suppliers",
        "payments", "supplier_payments", "audit_logs",
    ]
    for table in company_only:
        op.add_column(table, sa.Column("company_id", sa.Integer(), nullable=True))
        bind.execute(sa.text(
            f"UPDATE {table} SET company_id = :company_id WHERE company_id IS NULL"
        ), {"company_id": company_id})
        with op.batch_alter_table(table) as batch:
            batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(f"fk_{table}_company_id_companies", "companies", ["company_id"], ["id"])

    branch_warehouse_tables = {
        "invoices": ("company_id", "branch_id", "warehouse_id"),
        "purchases": ("company_id", "branch_id", "warehouse_id"),
        "stock_movements": ("company_id", "branch_id", "warehouse_id"),
    }
    for table, columns in branch_warehouse_tables.items():
        for column in columns:
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
        bind.execute(sa.text(
            f"UPDATE {table} SET company_id = :company_id, branch_id = :branch_id, "
            "warehouse_id = :warehouse_id"
        ), {
            "company_id": company_id,
            "branch_id": branch_id,
            "warehouse_id": warehouse_id,
        })
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(column, existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(f"fk_{table}_company_id_companies", "companies", ["company_id"], ["id"])
            batch.create_foreign_key(f"fk_{table}_branch_id_branches", "branches", ["branch_id"], ["id"])
            batch.create_foreign_key(f"fk_{table}_warehouse_id_warehouses", "warehouses", ["warehouse_id"], ["id"])

    # Product stock becomes available in the default warehouse without losing
    # the legacy aggregate quantity.
    op.add_column("product_stock", sa.Column("company_id", sa.Integer(), nullable=True))
    bind.execute(sa.text(
        "UPDATE product_stock SET company_id = :company_id WHERE company_id IS NULL"
    ), {"company_id": company_id})
    with op.batch_alter_table("product_stock") as batch:
        batch.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_product_stock_company_id_companies", "companies", ["company_id"], ["id"])

    bind.execute(sa.text(
        "INSERT INTO product_stock (product_id, warehouse_id, company_id, quantity, reorder_level, updated_at) "
        "SELECT id, :warehouse_id, :company_id, stock_qty, reorder_level, CURRENT_TIMESTAMP "
        "FROM products WHERE NOT EXISTS "
        "(SELECT 1 FROM product_stock ps WHERE ps.product_id = products.id AND ps.warehouse_id = :warehouse_id)"
    ), {"warehouse_id": warehouse_id, "company_id": company_id})

    # Give existing users access to the migrated company and its main branch.
    bind.execute(sa.text(
        "INSERT INTO user_company_access (user_id, company_id, is_default) "
        "SELECT id, :company_id, 1 FROM users "
        "WHERE NOT EXISTS (SELECT 1 FROM user_company_access a WHERE a.user_id = users.id AND a.company_id = :company_id)"
    ), {"company_id": company_id})
    bind.execute(sa.text(
        "INSERT INTO branch_access (user_id, branch_id) "
        "SELECT id, :branch_id FROM users "
        "WHERE NOT EXISTS (SELECT 1 FROM branch_access a WHERE a.user_id = users.id AND a.branch_id = :branch_id)"
    ), {"branch_id": branch_id})


def downgrade() -> None:
    # Ownership data is not safely reversible after companies are added.
    raise RuntimeError("This migration is intentionally irreversible to protect company ownership data.")
