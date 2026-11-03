from __future__ import annotations
from pathlib import Path
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import os
from sqlalchemy import (
    create_engine, String, Integer, Boolean, DateTime, ForeignKey, Numeric,
    Text, UniqueConstraint, select, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

APP_DIR = Path(__file__).resolve().parent.parent
DB_PATH = APP_DIR / "gst_billing.db"

# Desktop installations keep using the existing local SQLite database by
# default. Cloud deployments set ERP_DATABASE_URL to PostgreSQL.
from .saas.config import get_database_url, engine_options

DATABASE_URL = get_database_url()
engine = create_engine(DATABASE_URL, **engine_options(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

class Base(DeclarativeBase):
    pass

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(180), default="")
    gstin: Mapped[str] = mapped_column(String(15), default="")
    state_code: Mapped[str] = mapped_column(String(2), default="32")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(180), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_branch_company_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("branch_id", "code", name="uq_warehouse_branch_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    address: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserCompanyAccess(Base):
    __tablename__ = "user_company_access"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_company_access"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class BranchAccess(Base):
    __tablename__ = "branch_access"
    __table_args__ = (UniqueConstraint("user_id", "branch_id", name="uq_user_branch_access"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)


class ProductStock(Base):
    __tablename__ = "product_stock"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_product_stock_warehouse"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, nullable=False)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BusinessSettings(Base):
    __tablename__ = "business_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(180), default="Your Business Name")
    gstin: Mapped[str] = mapped_column(String(15), default="")
    state_code: Mapped[str] = mapped_column(String(2), default="32")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    invoice_prefix: Mapped[str] = mapped_column(String(20), default="INV")
    logo_path: Mapped[str] = mapped_column(Text, default="")
    next_invoice_number: Mapped[int] = mapped_column(Integer, default=1)
    smtp_host: Mapped[str] = mapped_column(String(180), default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_email: Mapped[str] = mapped_column(String(180), default="")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="staff")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SaaSTenant(Base):
    __tablename__ = "saas_tenants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SaaSTenantCompany(Base):
    """One-to-one link from a SaaS workspace to its operational ERP company."""
    __tablename__ = "saas_tenant_companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("saas_tenants.id"), nullable=False, unique=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), nullable=False, unique=True
    )
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class SaaSBusinessProfile(Base):
    """Tenant-scoped onboarding profile; separate from legacy desktop Company."""
    __tablename__ = "saas_business_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_saas_business_profile_tenant"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("saas_tenants.id"), nullable=False
    )
    trade_name: Mapped[str] = mapped_column(String(180), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(180), default="", nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), default="", nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    gst_registration_type: Mapped[str] = mapped_column(
        String(30), default="regular", nullable=False
    )
    financial_year_start_month: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    first_branch_name: Mapped[str] = mapped_column(String(180), default="Main Branch", nullable=False)
    first_warehouse_name: Mapped[str] = mapped_column(String(180), default="Main Warehouse", nullable=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class SaaSIdentity(Base):
    __tablename__ = "saas_identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SaaSTenantMembership(Base):
    __tablename__ = "saas_tenant_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "identity_id", name="uq_saas_tenant_identity"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("saas_tenants.id"), nullable=False)
    identity_id: Mapped[int] = mapped_column(ForeignKey("saas_identities.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="owner", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SaaSRefreshSession(Base):
    __tablename__ = "saas_refresh_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("saas_tenants.id"), nullable=False)
    identity_id: Mapped[int] = mapped_column(ForeignKey("saas_identities.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), default="")
    state_code: Mapped[str] = mapped_column(String(2), default="32")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(180), default="")
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=10000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    hsn_sac: Mapped[str] = mapped_column(String(20), default="")
    unit: Mapped[str] = mapped_column(String(20), default="Nos")
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=18)
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), default=1, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), default=1, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    invoice_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    seller_state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    place_of_supply_state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    is_interstate: Mapped[bool] = mapped_column(Boolean, default=False)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="issued")
    created_by: Mapped[str] = mapped_column(String(80), default="admin")
    customer: Mapped[Customer] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    sku_snapshot: Mapped[str] = mapped_column(String(80), default="")
    description_snapshot: Mapped[str] = mapped_column(String(180), nullable=False)
    hsn_sac_snapshot: Mapped[str] = mapped_column(String(20), default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), default="Nos")
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    gst_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    invoice: Mapped[Invoice] = relationship(back_populates="items")

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(30), default="UPI")
    reference: Mapped[str] = mapped_column(String(100), default="")
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    recorded_by: Mapped[str] = mapped_column(String(80), default="admin")
    invoice: Mapped[Invoice] = relationship(back_populates="payments")

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), default="")
    state_code: Mapped[str] = mapped_column(String(2), default="32")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), default=1, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), default=1, nullable=False)
    purchase_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    supplier_invoice_number: Mapped[str] = mapped_column(String(80), default="")
    purchase_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    created_by: Mapped[str] = mapped_column(String(80), default="admin")
    supplier: Mapped[Supplier] = relationship()
    items: Mapped[list["PurchaseItem"]] = relationship(back_populates="purchase", cascade="all, delete-orphan")
    payments: Mapped[list["SupplierPayment"]] = relationship(back_populates="purchase", cascade="all, delete-orphan")

class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(30), default="Bank transfer")
    reference: Mapped[str] = mapped_column(String(100), default="")
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    recorded_by: Mapped[str] = mapped_column(String(80), default="admin")
    purchase: Mapped[Purchase] = relationship(back_populates="payments")

class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(80), default="")
    description_snapshot: Mapped[str] = mapped_column(String(180), nullable=False)
    hsn_sac_snapshot: Mapped[str] = mapped_column(String(20), default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gst_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    purchase: Mapped[Purchase] = relationship(back_populates="items")

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), default=1, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), default=1, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    reference: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(80), default="admin")

class StockTransfer(Base):
    __tablename__ = "stock_transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    transfer_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(80), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=1, nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str] = mapped_column(String(50), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

def hash_password(password: str) -> str:
    # PBKDF2 is included in Python's standard library; use a unique salt per password.
    import secrets
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000).hex()
    return f"{salt}${digest}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000).hex()
        import hmac
        return hmac.compare_digest(actual, digest)
    except ValueError:
        return False

def init_db():
    Base.metadata.create_all(engine)
    # Safe additive migration for databases created before credit limits existed.
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "customers" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("customers")}
        if "credit_limit" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE customers ADD COLUMN credit_limit NUMERIC(14, 2) NOT NULL DEFAULT 10000"))
    inspector = inspect(engine)
    if "purchases" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("purchases")}
        if "amount_paid" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE purchases ADD COLUMN amount_paid NUMERIC(14, 2) NOT NULL DEFAULT 0"))
    inspector = inspect(engine)
    if "business_settings" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("business_settings")}
        with engine.begin() as connection:
            if "logo_path" not in columns:
                connection.execute(text("ALTER TABLE business_settings ADD COLUMN logo_path TEXT NOT NULL DEFAULT ''"))
            if "smtp_host" not in columns:
                connection.execute(text("ALTER TABLE business_settings ADD COLUMN smtp_host VARCHAR(180) NOT NULL DEFAULT 'smtp.gmail.com'"))
            if "smtp_port" not in columns:
                connection.execute(text("ALTER TABLE business_settings ADD COLUMN smtp_port INTEGER NOT NULL DEFAULT 587"))
            if "smtp_email" not in columns:
                connection.execute(text("ALTER TABLE business_settings ADD COLUMN smtp_email VARCHAR(180) NOT NULL DEFAULT ''"))
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(User)) == 0:
            session.add(User(username="admin", password_hash=hash_password("ChangeMe123!"), role="admin"))
        if session.scalar(select(func.count()).select_from(BusinessSettings)) == 0:
            session.add(BusinessSettings())
        session.commit()

def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def qty(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
