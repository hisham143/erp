"""Initial cloud API: health checks and tenant-scoped authentication."""
from __future__ import annotations

import os
import re
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import uuid
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import (
    SessionLocal, Branch, BusinessSettings, Company, SaaSBusinessProfile,
    SaaSIdentity, SaaSRefreshSession, SaaSTenant, SaaSTenantCompany,
    SaaSTenantMembership, Warehouse, Customer, Product, ProductStock, StockMovement,
    AuditLog, Supplier, Invoice, InvoiceItem, Payment, Purchase, PurchaseItem, SupplierPayment,
    hash_password, verify_password,
)
from app.saas.security import (
    ACCESS_TOKEN_SECONDS, REFRESH_TOKEN_DAYS, create_access_token,
    create_refresh_token, decode_access_token, hash_refresh_token,
)

app = FastAPI(
    title="ERP Cloud API",
    version="0.2.0",
    description="Multi-tenant ERP API foundation for the India SaaS product.",
)
bearer = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=180)
    owner_name: str = Field(min_length=2, max_length=180)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    tenant_slug: str = Field(min_length=2, max_length=80)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=40, max_length=200)



class SalesInvoiceItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)


class SalesInvoiceRequest(BaseModel):
    customer_id: int = Field(gt=0)
    invoice_date: date | None = None
    place_of_supply_state_code: str | None = Field(default=None, min_length=2, max_length=2)
    items: list[SalesInvoiceItemRequest] = Field(min_length=1, max_length=200)


class PurchaseBillItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)


class PurchaseBillRequest(BaseModel):
    supplier_id: int = Field(gt=0)
    supplier_invoice_number: str = Field(default="", max_length=80)
    purchase_date: date | None = None
    items: list[PurchaseBillItemRequest] = Field(min_length=1, max_length=200)


class SupplierPaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: str = Field(default="Bank transfer", min_length=2, max_length=30)
    reference: str = Field(default="", max_length=100)
    paid_at: datetime | None = None


class SalesPaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: str = Field(default="UPI", min_length=2, max_length=30)
    reference: str = Field(default="", max_length=100)
    paid_at: datetime | None = None


class MembershipRoleRequest(BaseModel):
    role: str = Field(min_length=3, max_length=30)


class BusinessOnboardingRequest(BaseModel):
    trade_name: str = Field(min_length=2, max_length=180)
    legal_name: str = Field(default="", max_length=180)
    gstin: str = Field(default="", max_length=15)
    state_code: str = Field(min_length=2, max_length=2)
    gst_registration_type: str = Field(default="regular", max_length=30)
    financial_year_start_month: int = Field(default=4, ge=1, le=12)
    address: str = Field(default="", max_length=2000)
    phone: str = Field(default="", max_length=30)
    first_branch_name: str = Field(default="Main Branch", min_length=2, max_length=180)
    first_warehouse_name: str = Field(default="Main Warehouse", min_length=2, max_length=180)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def _normal_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return email


def _slug(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")[:60]
    return f"{base or 'business'}-{create_refresh_token()[:6].lower()}"


def _set_refresh_cookie(response: Response, token: str | None) -> None:
    """Keep rotating refresh credentials out of browser JavaScript storage."""
    secure = os.getenv("ERP_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"}
    if token:
        response.set_cookie(
            key="erp_refresh",
            value=token,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/auth",
            max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        )
    else:
        response.delete_cookie(
            key="erp_refresh", path="/auth", httponly=True,
            secure=secure, samesite="lax",
        )


def _issue_tokens(session: Session, identity: SaaSIdentity, tenant: SaaSTenant) -> dict:
    refresh = create_refresh_token()
    session.add(SaaSRefreshSession(
        tenant_id=tenant.id,
        identity_id=identity.id,
        token_hash=hash_refresh_token(refresh),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS),
    ))
    return {
        "access_token": create_access_token(identity.id, tenant.id),
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_SECONDS,
        "tenant": {"id": tenant.id, "name": tenant.name, "slug": tenant.slug},
        "user": {"id": identity.id, "name": identity.full_name, "email": identity.email},
    }


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready(session: Session = Depends(get_db)):
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is not ready.") from exc
    return {"status": "ready", "database": "reachable"}


@app.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["authentication"])
def register(payload: RegisterRequest, response: Response, session: Session = Depends(get_db)):
    """Create a new SaaS tenant and its first owner atomically."""
    email = _normal_email(payload.email)
    if len(payload.password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters.")
    if session.scalar(select(SaaSIdentity.id).where(SaaSIdentity.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    try:
        tenant = SaaSTenant(name=payload.tenant_name.strip(), slug=_slug(payload.tenant_name))
        identity = SaaSIdentity(
            email=email,
            full_name=payload.owner_name.strip(),
            password_hash=hash_password(payload.password),
        )
        session.add_all([tenant, identity])
        session.flush()
        session.add(SaaSTenantMembership(
            tenant_id=tenant.id, identity_id=identity.id, role="owner", active=True
        ))
        result = _issue_tokens(session, identity, tenant)
        session.commit()
        _set_refresh_cookie(response, result["refresh_token"])
        return result
    except RuntimeError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Unable to create this account. Check whether the email is already registered.") from exc
    except Exception:
        session.rollback()
        raise


@app.post("/auth/login", tags=["authentication"])
def login(payload: LoginRequest, response: Response, session: Session = Depends(get_db)):
    email = _normal_email(payload.email)
    identity = session.scalar(select(SaaSIdentity).where(
        SaaSIdentity.email == email, SaaSIdentity.active.is_(True)
    ))
    tenant = session.scalar(select(SaaSTenant).where(
        SaaSTenant.slug == payload.tenant_slug.strip().lower(),
        SaaSTenant.active.is_(True),
    ))
    membership = None
    if identity and tenant:
        membership = session.scalar(select(SaaSTenantMembership).where(
            SaaSTenantMembership.identity_id == identity.id,
            SaaSTenantMembership.tenant_id == tenant.id,
            SaaSTenantMembership.active.is_(True),
        ))
    if not identity or not tenant or not membership or not verify_password(payload.password, identity.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email, password, or workspace.")
    try:
        result = _issue_tokens(session, identity, tenant)
        session.commit()
        _set_refresh_cookie(response, result["refresh_token"])
        return result
    except RuntimeError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/auth/refresh", tags=["authentication"])
def refresh(request: Request, response: Response, payload: RefreshRequest | None = None, session: Session = Depends(get_db)):
    refresh_token = (payload.refresh_token if payload else None) or request.cookies.get("erp_refresh")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token is missing.")
    token_hash = hash_refresh_token(refresh_token)
    stored = session.scalar(select(SaaSRefreshSession).where(
        SaaSRefreshSession.token_hash == token_hash,
        SaaSRefreshSession.revoked_at.is_(None),
    ))
    now = datetime.utcnow()
    if not stored or stored.expires_at <= now:
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired.")
    identity = session.scalar(select(SaaSIdentity).where(
        SaaSIdentity.id == stored.identity_id, SaaSIdentity.active.is_(True)
    ))
    tenant = session.scalar(select(SaaSTenant).where(
        SaaSTenant.id == stored.tenant_id, SaaSTenant.active.is_(True)
    ))
    membership = session.scalar(select(SaaSTenantMembership).where(
        SaaSTenantMembership.identity_id == stored.identity_id,
        SaaSTenantMembership.tenant_id == stored.tenant_id,
        SaaSTenantMembership.active.is_(True),
    ))
    if not identity or not tenant or not membership:
        stored.revoked_at = now
        session.commit()
        raise HTTPException(status_code=401, detail="Account or workspace is inactive.")
    try:
        # Atomic compare-and-set prevents two concurrent refresh requests from
        # successfully rotating the same refresh token.
        rotated = session.execute(
            update(SaaSRefreshSession)
            .where(
                SaaSRefreshSession.id == stored.id,
                SaaSRefreshSession.revoked_at.is_(None),
                SaaSRefreshSession.expires_at > now,
            )
            .values(revoked_at=now)
        )
        if rotated.rowcount != 1:
            session.rollback()
            raise HTTPException(
                status_code=401,
                detail="Refresh token is invalid or has already been used.",
            )
        result = _issue_tokens(session, identity, tenant)
        session.commit()
        _set_refresh_cookie(response, result["refresh_token"])
        return result
    except RuntimeError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc



@app.post("/auth/logout", tags=["authentication"])
def logout(request: Request, response: Response, payload: RefreshRequest | None = None, session: Session = Depends(get_db)):
    """Revoke the supplied refresh session and clear its browser cookie."""
    refresh_token = (payload.refresh_token if payload else None) or request.cookies.get("erp_refresh")
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        stored = session.scalar(select(SaaSRefreshSession).where(
            SaaSRefreshSession.token_hash == token_hash,
            SaaSRefreshSession.revoked_at.is_(None),
        ))
        if stored:
            stored.revoked_at = datetime.utcnow()
            session.commit()
    _set_refresh_cookie(response, None)
    return {"status": "signed_out"}


def current_membership(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_db),
):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        claims = decode_access_token(credentials.credentials)
        identity_id = int(claims["sub"])
        tenant_id = int(claims["tid"])
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc
    row = session.execute(
        select(SaaSIdentity, SaaSTenant, SaaSTenantMembership)
        .join(SaaSTenantMembership, SaaSTenantMembership.identity_id == SaaSIdentity.id)
        .join(SaaSTenant, SaaSTenant.id == SaaSTenantMembership.tenant_id)
        .where(
            SaaSIdentity.id == identity_id,
            SaaSIdentity.active.is_(True),
            SaaSTenant.id == tenant_id,
            SaaSTenant.active.is_(True),
            SaaSTenantMembership.active.is_(True),
        )
    ).first()
    if not row:
        raise HTTPException(status_code=401, detail="Account or workspace access is inactive.")
    identity, tenant, membership = row
    return {
        "user_id": identity.id,
        "email": identity.email,
        "full_name": identity.full_name,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "role": membership.role,
    }



_GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
)
_GST_REGISTRATION_TYPES = {"regular", "composition", "unregistered", "casual", "sez"}


def _ensure_operational_company(
    session: Session, tenant_id: int, profile: SaaSBusinessProfile
) -> SaaSTenantCompany:
    """Create the operational company hierarchy once, within the profile transaction."""
    linked = session.scalar(select(SaaSTenantCompany).where(
        SaaSTenantCompany.tenant_id == tenant_id
    ))
    if linked:
        company = session.get(Company, linked.company_id)
        branch = session.get(Branch, linked.branch_id)
        warehouse = session.get(Warehouse, linked.warehouse_id)
        if not company or not branch or not warehouse:
            raise HTTPException(
                status_code=409,
                detail="Workspace ERP setup is incomplete; contact support before retrying.",
            )
        # Keep operational master details aligned when an owner edits onboarding.
        company.name = profile.trade_name
        company.legal_name = profile.legal_name
        company.gstin = profile.gstin
        company.state_code = profile.state_code
        company.address = profile.address
        company.phone = profile.phone
        branch.name = profile.first_branch_name
        branch.address = profile.address
        branch.phone = profile.phone
        warehouse.name = profile.first_warehouse_name
        settings = session.scalar(select(BusinessSettings).where(
            BusinessSettings.company_id == company.id
        ))
        if settings is None:
            settings = BusinessSettings(company_id=company.id)
            session.add(settings)
        settings.legal_name = profile.legal_name or profile.trade_name
        settings.gstin = profile.gstin
        settings.state_code = profile.state_code
        settings.address = profile.address
        settings.phone = profile.phone
        return linked

    company = Company(
        name=profile.trade_name,
        legal_name=profile.legal_name,
        gstin=profile.gstin,
        state_code=profile.state_code,
        address=profile.address,
        phone=profile.phone,
        active=True,
    )
    session.add(company)
    session.flush()
    branch = Branch(
        company_id=company.id, name=profile.first_branch_name,
        code="MAIN", address=profile.address, phone=profile.phone, active=True,
    )
    session.add(branch)
    session.flush()
    warehouse = Warehouse(
        company_id=company.id, branch_id=branch.id,
        name=profile.first_warehouse_name, code="MAIN", address=profile.address,
        active=True,
    )
    session.add(warehouse)
    session.add(BusinessSettings(
        company_id=company.id,
        legal_name=profile.legal_name or profile.trade_name,
        gstin=profile.gstin, state_code=profile.state_code,
        address=profile.address, phone=profile.phone,
    ))
    session.flush()
    linked = SaaSTenantCompany(
        tenant_id=tenant_id, company_id=company.id,
        branch_id=branch.id, warehouse_id=warehouse.id,
    )
    session.add(linked)
    session.flush()
    return linked


def _erp_setup_payload(session: Session, linked: SaaSTenantCompany) -> dict:
    company = session.get(Company, linked.company_id)
    branch = session.get(Branch, linked.branch_id)
    warehouse = session.get(Warehouse, linked.warehouse_id)
    return {
        "company": {"id": company.id, "name": company.name},
        "branch": {"id": branch.id, "name": branch.name, "code": branch.code},
        "warehouse": {
            "id": warehouse.id, "name": warehouse.name, "code": warehouse.code
        },
    }


def _business_profile_payload(profile: SaaSBusinessProfile) -> dict:
    return {
        "trade_name": profile.trade_name,
        "legal_name": profile.legal_name,
        "gstin": profile.gstin,
        "state_code": profile.state_code,
        "gst_registration_type": profile.gst_registration_type,
        "financial_year_start_month": profile.financial_year_start_month,
        "address": profile.address,
        "phone": profile.phone,
        "first_branch_name": profile.first_branch_name,
        "first_warehouse_name": profile.first_warehouse_name,
        "onboarding_completed": profile.onboarding_completed,
    }


@app.get("/onboarding/business", tags=["onboarding"])
def get_business_onboarding(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    profile = session.scalar(select(SaaSBusinessProfile).where(
        SaaSBusinessProfile.tenant_id == membership["tenant_id"]
    ))
    if not profile:
        raise HTTPException(status_code=404, detail="Business onboarding has not been saved.")
    result = _business_profile_payload(profile)
    linked = session.scalar(select(SaaSTenantCompany).where(
        SaaSTenantCompany.tenant_id == membership["tenant_id"]
    ))
    if linked:
        result["erp_setup"] = _erp_setup_payload(session, linked)
    return result


@app.put("/onboarding/business", tags=["onboarding"])
def save_business_onboarding(
    payload: BusinessOnboardingRequest,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    if membership["role"] not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only a tenant owner or admin can edit business setup.")

    trade_name = payload.trade_name.strip()
    state_code = payload.state_code.strip()
    gstin = payload.gstin.strip().upper()
    registration_type = payload.gst_registration_type.strip().lower()
    if len(trade_name) < 2:
        raise HTTPException(status_code=422, detail="Enter a valid business name.")
    if not re.fullmatch(r"[0-9]{2}", state_code):
        raise HTTPException(status_code=422, detail="State code must contain exactly two digits.")
    if registration_type not in _GST_REGISTRATION_TYPES:
        raise HTTPException(status_code=422, detail="Select a supported GST registration type.")
    if gstin:
        if not _GSTIN_PATTERN.fullmatch(gstin):
            raise HTTPException(status_code=422, detail="GSTIN format is invalid.")
        if gstin[:2] != state_code:
            raise HTTPException(status_code=422, detail="GSTIN state code must match the selected state.")
    elif registration_type in {"regular", "composition", "casual", "sez"}:
        raise HTTPException(status_code=422, detail="Enter GSTIN or select Unregistered.")

    profile = session.scalar(select(SaaSBusinessProfile).where(
        SaaSBusinessProfile.tenant_id == membership["tenant_id"]
    ))
    if profile is None:
        profile = SaaSBusinessProfile(
            tenant_id=membership["tenant_id"],
            trade_name=trade_name,
            state_code=state_code,
        )
        session.add(profile)

    profile.trade_name = trade_name
    profile.legal_name = payload.legal_name.strip()
    profile.gstin = gstin
    profile.state_code = state_code
    profile.gst_registration_type = registration_type
    profile.financial_year_start_month = payload.financial_year_start_month
    profile.address = payload.address.strip()
    profile.phone = payload.phone.strip()
    profile.first_branch_name = payload.first_branch_name.strip()
    profile.first_warehouse_name = payload.first_warehouse_name.strip()
    profile.onboarding_completed = bool(
        trade_name and state_code and profile.first_branch_name and profile.first_warehouse_name
    )
    try:
        session.flush()
        linked = _ensure_operational_company(session, membership["tenant_id"], profile)
        session.commit()
        session.refresh(profile)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Business setup could not be saved.") from exc
    result = _business_profile_payload(profile)
    result["erp_setup"] = _erp_setup_payload(session, linked)
    return result

@app.get("/onboarding/erp-setup", tags=["onboarding"])
def get_erp_setup(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = session.scalar(select(SaaSTenantCompany).where(
        SaaSTenantCompany.tenant_id == membership["tenant_id"]
    ))
    if not linked:
        raise HTTPException(status_code=404, detail="ERP company setup is not complete.")
    return _erp_setup_payload(session, linked)

_TENANT_ROLES = {"owner", "admin", "manager", "accountant", "sales", "staff"}


def _tenant_erp_context(session: Session, tenant_id: int) -> SaaSTenantCompany:
    linked = session.scalar(select(SaaSTenantCompany).where(
        SaaSTenantCompany.tenant_id == tenant_id
    ))
    if not linked:
        raise HTTPException(status_code=409, detail="Complete business setup before using ERP modules.")
    company = session.get(Company, linked.company_id)
    branch = session.get(Branch, linked.branch_id)
    warehouse = session.get(Warehouse, linked.warehouse_id)
    if (
        not company or not company.active or not branch or not branch.active
        or not warehouse or not warehouse.active
        or branch.company_id != company.id
        or warehouse.company_id != company.id
        or warehouse.branch_id != branch.id
    ):
        raise HTTPException(status_code=409, detail="Workspace ERP context is inactive or inconsistent.")
    return linked


def _require_roles(membership: dict, *roles: str) -> None:
    if membership["role"] not in set(roles):
        raise HTTPException(status_code=403, detail="Your workspace role cannot perform this action.")


@app.get("/workspace/members", tags=["workspace"])
def list_workspace_members(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin")
    rows = session.execute(
        select(SaaSIdentity, SaaSTenantMembership)
        .join(SaaSTenantMembership, SaaSTenantMembership.identity_id == SaaSIdentity.id)
        .where(SaaSTenantMembership.tenant_id == membership["tenant_id"])
        .order_by(SaaSIdentity.full_name, SaaSIdentity.id)
    ).all()
    return {"items": [
        {
            "identity_id": identity.id,
            "name": identity.full_name,
            "email": identity.email,
            "role": member.role,
            "active": bool(identity.active and member.active),
        }
        for identity, member in rows
    ]}


@app.patch("/workspace/members/{identity_id}/role", tags=["workspace"])
def update_workspace_member_role(
    identity_id: int,
    payload: MembershipRoleRequest,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner")
    new_role = payload.role.strip().lower()
    if new_role not in _TENANT_ROLES - {"owner"}:
        raise HTTPException(status_code=422, detail="Select a supported non-owner role.")
    target = session.scalar(select(SaaSTenantMembership).where(
        SaaSTenantMembership.tenant_id == membership["tenant_id"],
        SaaSTenantMembership.identity_id == identity_id,
        SaaSTenantMembership.active.is_(True),
    ))
    if not target:
        raise HTTPException(status_code=404, detail="Active workspace member not found.")
    if target.role == "owner":
        raise HTTPException(status_code=409, detail="Owner role cannot be changed through this endpoint.")
    target.role = new_role
    session.commit()
    return {"identity_id": identity_id, "role": new_role}


@app.get("/erp/context", tags=["erp"])
def get_current_erp_context(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    return _erp_setup_payload(session, linked)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _invoice_payload(invoice: Invoice) -> dict:
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.date().isoformat(),
        "customer_id": invoice.customer_id,
        "seller_state_code": invoice.seller_state_code,
        "place_of_supply_state_code": invoice.place_of_supply_state_code,
        "is_interstate": invoice.is_interstate,
        "taxable_total": str(invoice.taxable_total),
        "cgst_total": str(invoice.cgst_total),
        "sgst_total": str(invoice.sgst_total),
        "igst_total": str(invoice.igst_total),
        "grand_total": str(invoice.grand_total),
        "amount_paid": str(invoice.amount_paid),
        "status": invoice.status,
        "balance_due": str(_money(Decimal(invoice.grand_total) - Decimal(invoice.amount_paid))),
        "payments": [{
            "id": payment.id, "amount": str(payment.amount),
            "method": payment.method, "reference": payment.reference,
            "paid_at": payment.paid_at.isoformat(),
        } for payment in invoice.payments],
        "items": [{
            "id": item.id, "product_id": item.product_id,
            "sku": item.sku_snapshot, "description": item.description_snapshot,
            "hsn_sac": item.hsn_sac_snapshot, "unit": item.unit_snapshot,
            "quantity": str(item.quantity), "unit_price": str(item.unit_price),
            "discount_amount": str(item.discount_amount),
            "gst_rate": str(item.gst_rate_snapshot),
            "taxable_value": str(item.taxable_value),
            "cgst_amount": str(item.cgst_amount),
            "sgst_amount": str(item.sgst_amount),
            "igst_amount": str(item.igst_amount),
            "line_total": str(item.line_total),
        } for item in invoice.items],
    }


@app.post("/erp/sales/invoices", status_code=status.HTTP_201_CREATED, tags=["sales"])
def create_sales_invoice(
    payload: SalesInvoiceRequest,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin", "manager", "accountant", "sales")
    linked = _tenant_erp_context(session, membership["tenant_id"])
    customer = session.scalar(select(Customer).where(
        Customer.id == payload.customer_id,
        Customer.company_id == linked.company_id,
        Customer.active.is_(True),
    ))
    if not customer:
        raise HTTPException(status_code=404, detail="Active customer not found in this workspace.")
    company = session.get(Company, linked.company_id)
    seller_state = (company.state_code or "").strip()
    supply_state = (payload.place_of_supply_state_code or customer.state_code or "").strip()
    if not re.fullmatch(r"[0-9]{2}", seller_state) or not re.fullmatch(r"[0-9]{2}", supply_state):
        raise HTTPException(status_code=409, detail="Seller and place-of-supply state codes must be configured.")
    interstate = seller_state != supply_state
    invoice_date = datetime.combine(payload.invoice_date or date.today(), time.min)
    invoice = Invoice(
        company_id=linked.company_id,
        branch_id=linked.branch_id,
        warehouse_id=linked.warehouse_id,
        invoice_number=f"PENDING-{uuid.uuid4().hex}",
        invoice_date=invoice_date,
        customer_id=customer.id,
        seller_state_code=seller_state,
        place_of_supply_state_code=supply_state,
        is_interstate=interstate,
        status="issued",
        created_by=membership["email"][:80],
    )
    taxable_total = cgst_total = sgst_total = igst_total = grand_total = Decimal("0")
    try:
        for requested in payload.items:
            product = session.scalar(select(Product).where(
                Product.id == requested.product_id,
                Product.company_id == linked.company_id,
                Product.active.is_(True),
            ))
            if not product:
                raise HTTPException(status_code=404, detail=f"Active product {requested.product_id} not found in this workspace.")
            quantity = Decimal(requested.quantity)
            unit_price = Decimal(requested.unit_price if requested.unit_price is not None else product.selling_price)
            discount = Decimal(requested.discount_amount)
            gross = _money(quantity * unit_price)
            if discount > gross:
                raise HTTPException(status_code=422, detail="Discount cannot exceed the line gross amount.")
            taxable = _money(gross - discount)
            rate = Decimal(product.gst_rate)
            if rate < 0 or rate > 100:
                raise HTTPException(status_code=409, detail=f"Product {product.id} has an invalid GST rate.")
            tax = _money(taxable * rate / Decimal("100"))
            cgst = sgst = Decimal("0.00")
            igst = Decimal("0.00")
            if interstate:
                igst = tax
            else:
                cgst = _money(tax / Decimal("2"))
                sgst = tax - cgst
            line_total = taxable + tax
            invoice.items.append(InvoiceItem(
                product_id=product.id,
                sku_snapshot=product.sku,
                description_snapshot=product.name,
                hsn_sac_snapshot=product.hsn_sac,
                unit_snapshot=product.unit,
                quantity=quantity,
                unit_price=unit_price,
                discount_amount=discount,
                gst_rate_snapshot=rate,
                taxable_value=taxable,
                cgst_amount=cgst,
                sgst_amount=sgst,
                igst_amount=igst,
                line_total=line_total,
            ))
            taxable_total += taxable
            cgst_total += cgst
            sgst_total += sgst
            igst_total += igst
            grand_total += line_total
        # Deduct stock once per product, aggregating duplicate invoice lines.
        quantities: dict[int, Decimal] = {}
        for line in invoice.items:
            if line.product_id is not None:
                quantities[line.product_id] = quantities.get(line.product_id, Decimal("0")) + Decimal(line.quantity)
        stock_rows: dict[int, ProductStock] = {}
        for product_id, requested_qty in quantities.items():
            product = session.scalar(select(Product).where(
                Product.id == product_id, Product.company_id == linked.company_id
            ).with_for_update())
            stock = session.scalar(select(ProductStock).where(
                ProductStock.company_id == linked.company_id,
                ProductStock.product_id == product_id,
                ProductStock.warehouse_id == linked.warehouse_id,
            ).with_for_update())
            if stock is None:
                # One-time bridge from the desktop aggregate stock field.
                stock = ProductStock(
                    company_id=linked.company_id, product_id=product_id,
                    warehouse_id=linked.warehouse_id,
                    quantity=Decimal(product.stock_qty or 0),
                    reorder_level=Decimal(product.reorder_level or 0),
                )
                session.add(stock)
                session.flush()
            available = Decimal(stock.quantity or 0)
            if available < requested_qty:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for product {product_id}. Available: {available}, requested: {requested_qty}.",
                )
            stock.quantity = available - requested_qty
            product.stock_qty = stock.quantity
            stock_rows[product_id] = stock

        invoice.taxable_total = _money(taxable_total)
        invoice.cgst_total = _money(cgst_total)
        invoice.sgst_total = _money(sgst_total)
        invoice.igst_total = _money(igst_total)
        invoice.grand_total = _money(grand_total)
        session.add(invoice)
        session.flush()
        invoice.invoice_number = f"INV-{linked.company_id}-{invoice.invoice_date:%Y%m%d}-{invoice.id:06d}"
        for product_id, quantity in quantities.items():
            session.add(StockMovement(
                company_id=linked.company_id, branch_id=linked.branch_id,
                warehouse_id=linked.warehouse_id, product_id=product_id,
                quantity_delta=-quantity, reason="sales_invoice",
                reference=invoice.invoice_number, created_by=membership["email"][:80],
            ))
        session.add(AuditLog(
            company_id=linked.company_id, username=membership["email"][:80],
            action="sales_invoice_created", entity_type="Invoice",
            entity_id=str(invoice.id),
            details=json.dumps({"invoice_number": invoice.invoice_number, "stock_deducted": {str(k): str(v) for k, v in quantities.items()}}),
        ))
        session.commit()
        session.refresh(invoice)
        return _invoice_payload(invoice)
    except HTTPException:
        session.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Sales invoice could not be saved.") from exc


@app.post("/erp/sales/invoices/{invoice_id}/payments", status_code=status.HTTP_201_CREATED, tags=["sales"])
def record_sales_payment(
    invoice_id: int,
    payload: SalesPaymentRequest,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin", "manager", "accountant", "sales")
    linked = _tenant_erp_context(session, membership["tenant_id"])
    invoice = session.scalar(select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.company_id == linked.company_id,
    ).with_for_update())
    if not invoice:
        raise HTTPException(status_code=404, detail="Sales invoice not found.")
    if invoice.status in {"cancelled", "void", "draft"}:
        raise HTTPException(status_code=409, detail="Payments cannot be recorded against this invoice.")
    amount = _money(Decimal(payload.amount))
    current_paid = _money(Decimal(invoice.amount_paid))
    grand_total = _money(Decimal(invoice.grand_total))
    balance = _money(grand_total - current_paid)
    if balance <= 0:
        raise HTTPException(status_code=409, detail="This invoice is already fully paid.")
    if amount > balance:
        raise HTTPException(status_code=422, detail="Payment cannot exceed the invoice balance due.")
    method = payload.method.strip()
    if len(method) < 2:
        raise HTTPException(status_code=422, detail="Enter a valid payment method.")
    reference = payload.reference.strip()
    if reference and session.scalar(select(Payment.id).where(
        Payment.company_id == linked.company_id,
        Payment.invoice_id == invoice.id,
        Payment.reference == reference,
    )):
        raise HTTPException(status_code=409, detail="This payment reference is already recorded for the invoice.")
    payment = Payment(
        company_id=linked.company_id,
        invoice_id=invoice.id,
        amount=amount,
        method=method,
        reference=reference,
        paid_at=payload.paid_at or datetime.now(),
        recorded_by=membership["email"][:80],
    )
    try:
        session.add(payment)
        invoice.amount_paid = _money(current_paid + amount)
        invoice.status = "paid" if invoice.amount_paid >= grand_total else "partially_paid"
        session.commit()
        session.refresh(invoice)
        return _invoice_payload(invoice)
    except (IntegrityError, SQLAlchemyError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Payment could not be recorded.") from exc


@app.post("/erp/sales/invoices/{invoice_id}/cancel", tags=["sales"])
def cancel_sales_invoice(
    invoice_id: int,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin", "manager", "accountant")
    linked = _tenant_erp_context(session, membership["tenant_id"])
    invoice = session.scalar(select(Invoice).where(
        Invoice.id == invoice_id, Invoice.company_id == linked.company_id
    ).with_for_update())
    if not invoice:
        raise HTTPException(status_code=404, detail="Sales invoice not found.")
    if invoice.status in {"cancelled", "void", "draft"}:
        raise HTTPException(status_code=409, detail="This invoice cannot be cancelled.")
    if Decimal(invoice.amount_paid or 0) != 0:
        raise HTTPException(
            status_code=409,
            detail="This invoice has recorded payments. Refund/reversal must be completed before cancellation.",
        )
    quantities: dict[int, Decimal] = {}
    for line in invoice.items:
        if line.product_id is not None:
            quantities[line.product_id] = quantities.get(line.product_id, Decimal("0")) + Decimal(line.quantity)
    try:
        for product_id, quantity in quantities.items():
            stock = session.scalar(select(ProductStock).where(
                ProductStock.company_id == linked.company_id,
                ProductStock.product_id == product_id,
                ProductStock.warehouse_id == invoice.warehouse_id,
            ).with_for_update())
            product = session.scalar(select(Product).where(
                Product.id == product_id, Product.company_id == linked.company_id
            ).with_for_update())
            if stock is None or product is None:
                raise HTTPException(status_code=409, detail=f"Stock record for product {product_id} is missing; cancellation was not applied.")
            stock.quantity = Decimal(stock.quantity or 0) + quantity
            product.stock_qty = stock.quantity
            session.add(StockMovement(
                company_id=linked.company_id, branch_id=invoice.branch_id,
                warehouse_id=invoice.warehouse_id, product_id=product_id,
                quantity_delta=quantity, reason="sales_invoice_cancel",
                reference=invoice.invoice_number, created_by=membership["email"][:80],
            ))
        invoice.status = "cancelled"
        session.add(AuditLog(
            company_id=linked.company_id, username=membership["email"][:80],
            action="sales_invoice_cancelled", entity_type="Invoice",
            entity_id=str(invoice.id),
            details=json.dumps({"invoice_number": invoice.invoice_number, "stock_restored": {str(k): str(v) for k, v in quantities.items()}}),
        ))
        session.commit()
        session.refresh(invoice)
        return _invoice_payload(invoice)
    except HTTPException:
        session.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Sales invoice cancellation could not be saved.") from exc


@app.get("/erp/sales/invoices", tags=["sales"])
def list_sales_invoices(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    rows = session.scalars(select(Invoice).where(
        Invoice.company_id == linked.company_id
    ).order_by(Invoice.invoice_date.desc(), Invoice.id.desc())).all()
    return {"items": [_invoice_payload(row) for row in rows]}


@app.get("/erp/sales/invoices/{invoice_id}", tags=["sales"])
def get_sales_invoice(
    invoice_id: int,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    invoice = session.scalar(select(Invoice).where(
        Invoice.id == invoice_id, Invoice.company_id == linked.company_id
    ))
    if not invoice:
        raise HTTPException(status_code=404, detail="Sales invoice not found.")
    return _invoice_payload(invoice)



def _purchase_payload(purchase: Purchase) -> dict:
    return {
        "id": purchase.id,
        "purchase_number": purchase.purchase_number,
        "supplier_invoice_number": purchase.supplier_invoice_number,
        "purchase_date": purchase.purchase_date.date().isoformat(),
        "supplier_id": purchase.supplier_id,
        "taxable_total": str(purchase.taxable_total),
        "cgst_total": str(purchase.cgst_total),
        "sgst_total": str(purchase.sgst_total),
        "igst_total": str(purchase.igst_total),
        "tax_total": str(purchase.tax_total),
        "grand_total": str(purchase.grand_total),
        "amount_paid": str(purchase.amount_paid),
        "balance_due": str(_money(Decimal(purchase.grand_total) - Decimal(purchase.amount_paid))),
        "status": purchase.status,
        "payments": [{
            "id": p.id, "amount": str(p.amount), "method": p.method,
            "reference": p.reference, "paid_at": p.paid_at.isoformat(),
        } for p in purchase.payments],
        "items": [{
            "id": item.id, "product_id": item.product_id,
            "sku": item.sku_snapshot, "description": item.description_snapshot,
            "hsn_sac": item.hsn_sac_snapshot,
            "quantity": str(item.quantity), "unit_cost": str(item.unit_cost),
            "discount_amount": str(item.discount_amount),
            "gst_rate": str(item.gst_rate_snapshot),
            "taxable_value": str(item.taxable_value),
            "cgst_amount": str(item.cgst_amount),
            "sgst_amount": str(item.sgst_amount),
            "igst_amount": str(item.igst_amount),
            "tax_amount": str(item.tax_amount), "line_total": str(item.line_total),
        } for item in purchase.items],
    }


@app.post("/erp/purchases/bills", status_code=status.HTTP_201_CREATED, tags=["purchases"])
def create_purchase_bill(
    payload: PurchaseBillRequest,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin", "manager", "accountant")
    linked = _tenant_erp_context(session, membership["tenant_id"])
    supplier = session.scalar(select(Supplier).where(
        Supplier.id == payload.supplier_id,
        Supplier.company_id == linked.company_id,
        Supplier.active.is_(True),
    ))
    if not supplier:
        raise HTTPException(status_code=404, detail="Active supplier not found in this workspace.")
    company = session.get(Company, linked.company_id)
    seller_state = (company.state_code or "").strip()
    supplier_state = (supplier.state_code or "").strip()
    if not re.fullmatch(r"[0-9]{2}", seller_state) or not re.fullmatch(r"[0-9]{2}", supplier_state):
        raise HTTPException(status_code=409, detail="Company and supplier state codes must be configured.")
    interstate = seller_state != supplier_state
    purchase = Purchase(
        company_id=linked.company_id, branch_id=linked.branch_id,
        warehouse_id=linked.warehouse_id, supplier_id=supplier.id,
        purchase_number=f"PENDING-{uuid.uuid4().hex}",
        supplier_invoice_number=payload.supplier_invoice_number.strip(),
        purchase_date=datetime.combine(payload.purchase_date or date.today(), time.min),
        status="received", created_by=membership["email"][:80],
    )
    taxable_total = cgst_total = sgst_total = igst_total = Decimal("0")
    try:
        for requested in payload.items:
            product = session.scalar(select(Product).where(
                Product.id == requested.product_id,
                Product.company_id == linked.company_id,
                Product.active.is_(True),
            ))
            if not product:
                raise HTTPException(status_code=404, detail=f"Active product {requested.product_id} not found in this workspace.")
            quantity = Decimal(requested.quantity)
            unit_cost = Decimal(requested.unit_cost)
            discount = Decimal(requested.discount_amount)
            gross = _money(quantity * unit_cost)
            if discount > gross:
                raise HTTPException(status_code=422, detail="Discount cannot exceed the line gross amount.")
            taxable = _money(gross - discount)
            rate = Decimal(product.gst_rate)
            if rate < 0 or rate > 100:
                raise HTTPException(status_code=409, detail=f"Product {product.id} has an invalid GST rate.")
            tax = _money(taxable * rate / Decimal("100"))
            cgst = sgst = igst = Decimal("0.00")
            if interstate:
                igst = tax
            else:
                cgst = _money(tax / Decimal("2"))
                sgst = tax - cgst
            purchase.items.append(PurchaseItem(
                product_id=product.id, sku_snapshot=product.sku,
                description_snapshot=product.name, hsn_sac_snapshot=product.hsn_sac,
                quantity=quantity, unit_cost=unit_cost, discount_amount=discount,
                gst_rate_snapshot=rate, taxable_value=taxable,
                cgst_amount=cgst, sgst_amount=sgst, igst_amount=igst,
                tax_amount=tax, line_total=taxable + tax,
            ))
            taxable_total += taxable
            cgst_total += cgst
            sgst_total += sgst
            igst_total += igst

        quantities: dict[int, Decimal] = {}
        for line in purchase.items:
            quantities[line.product_id] = quantities.get(line.product_id, Decimal("0")) + Decimal(line.quantity)
        for product_id, received_qty in quantities.items():
            product = session.scalar(select(Product).where(
                Product.id == product_id, Product.company_id == linked.company_id
            ).with_for_update())
            stock = session.scalar(select(ProductStock).where(
                ProductStock.company_id == linked.company_id,
                ProductStock.product_id == product_id,
                ProductStock.warehouse_id == linked.warehouse_id,
            ).with_for_update())
            if stock is None:
                stock = ProductStock(
                    company_id=linked.company_id, product_id=product_id,
                    warehouse_id=linked.warehouse_id,
                    quantity=Decimal(product.stock_qty or 0),
                    reorder_level=Decimal(product.reorder_level or 0),
                )
                session.add(stock)
                session.flush()
            stock.quantity = Decimal(stock.quantity or 0) + received_qty
            product.stock_qty = stock.quantity

        purchase.taxable_total = _money(taxable_total)
        purchase.cgst_total = _money(cgst_total)
        purchase.sgst_total = _money(sgst_total)
        purchase.igst_total = _money(igst_total)
        purchase.tax_total = _money(cgst_total + sgst_total + igst_total)
        purchase.grand_total = _money(taxable_total + purchase.tax_total)
        session.add(purchase)
        session.flush()
        purchase.purchase_number = f"PUR-{linked.company_id}-{purchase.purchase_date:%Y%m%d}-{purchase.id}"
        for product_id, received_qty in quantities.items():
            session.add(StockMovement(
                company_id=linked.company_id, branch_id=linked.branch_id,
                warehouse_id=linked.warehouse_id, product_id=product_id,
                quantity_delta=received_qty, reason="purchase_received",
                reference=purchase.purchase_number, created_by=membership["email"][:80],
            ))
        session.add(AuditLog(
            company_id=linked.company_id, username=membership["email"][:80],
            action="purchase_bill_created", entity_type="Purchase",
            entity_id=str(purchase.id),
            details=json.dumps({"purchase_number": purchase.purchase_number, "stock_received": {str(k): str(v) for k, v in quantities.items()}}),
        ))
        session.commit()
        session.refresh(purchase)
        return _purchase_payload(purchase)
    except HTTPException:
        session.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Purchase bill could not be saved.") from exc


@app.get("/erp/purchases/bills", tags=["purchases"])
def list_purchase_bills(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    rows = session.scalars(select(Purchase).where(
        Purchase.company_id == linked.company_id
    ).order_by(Purchase.purchase_date.desc(), Purchase.id.desc())).all()
    return {"items": [_purchase_payload(row) for row in rows]}


@app.get("/erp/purchases/bills/{purchase_id}", tags=["purchases"])
def get_purchase_bill(
    purchase_id: int,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    purchase = session.scalar(select(Purchase).where(
        Purchase.id == purchase_id, Purchase.company_id == linked.company_id
    ))
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase bill not found.")
    return _purchase_payload(purchase)


@app.post("/erp/purchases/bills/{purchase_id}/payments", status_code=status.HTTP_201_CREATED, tags=["purchases"])
def record_supplier_payment(
    purchase_id: int,
    payload: SupplierPaymentRequest,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin", "manager", "accountant")
    linked = _tenant_erp_context(session, membership["tenant_id"])
    purchase = session.scalar(select(Purchase).where(
        Purchase.id == purchase_id, Purchase.company_id == linked.company_id
    ).with_for_update())
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase bill not found.")
    if purchase.status != "received":
        raise HTTPException(status_code=409, detail="Payments can only be recorded against received purchases.")
    balance = _money(Decimal(purchase.grand_total) - Decimal(purchase.amount_paid))
    amount = _money(Decimal(payload.amount))
    if amount > balance:
        raise HTTPException(status_code=422, detail=f"Payment exceeds outstanding balance of {balance}.")
    reference = payload.reference.strip()
    if reference and session.scalar(select(SupplierPayment.id).where(
        SupplierPayment.purchase_id == purchase.id,
        SupplierPayment.reference == reference,
    )):
        raise HTTPException(status_code=409, detail="This payment reference already exists for the purchase.")
    try:
        session.add(SupplierPayment(
            company_id=linked.company_id, purchase_id=purchase.id, amount=amount,
            method=payload.method.strip(), reference=reference,
            paid_at=payload.paid_at or datetime.utcnow(),
            recorded_by=membership["email"][:80],
        ))
        purchase.amount_paid = _money(Decimal(purchase.amount_paid or 0) + amount)
        session.add(AuditLog(
            company_id=linked.company_id, username=membership["email"][:80],
            action="supplier_payment_recorded", entity_type="Purchase",
            entity_id=str(purchase.id),
            details=json.dumps({"amount": str(amount), "reference": reference}),
        ))
        session.commit()
        session.refresh(purchase)
        return _purchase_payload(purchase)
    except (IntegrityError, SQLAlchemyError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Supplier payment could not be saved.") from exc


@app.post("/erp/purchases/bills/{purchase_id}/cancel", tags=["purchases"])
def cancel_purchase_bill(
    purchase_id: int,
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    _require_roles(membership, "owner", "admin", "manager", "accountant")
    linked = _tenant_erp_context(session, membership["tenant_id"])
    purchase = session.scalar(select(Purchase).where(
        Purchase.id == purchase_id, Purchase.company_id == linked.company_id
    ).with_for_update())
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase bill not found.")
    if purchase.status != "received":
        raise HTTPException(status_code=409, detail="This purchase bill cannot be cancelled.")
    if Decimal(purchase.amount_paid or 0) != 0:
        raise HTTPException(status_code=409, detail="This purchase has supplier payments. Reverse/refund them before cancellation.")
    quantities: dict[int, Decimal] = {}
    for line in purchase.items:
        quantities[line.product_id] = quantities.get(line.product_id, Decimal("0")) + Decimal(line.quantity)
    try:
        for product_id, quantity in quantities.items():
            stock = session.scalar(select(ProductStock).where(
                ProductStock.company_id == linked.company_id,
                ProductStock.product_id == product_id,
                ProductStock.warehouse_id == purchase.warehouse_id,
            ).with_for_update())
            product = session.scalar(select(Product).where(
                Product.id == product_id, Product.company_id == linked.company_id
            ).with_for_update())
            if stock is None or product is None:
                raise HTTPException(status_code=409, detail=f"Stock record for product {product_id} is missing; cancellation was not applied.")
            available = Decimal(stock.quantity or 0)
            if available < quantity:
                raise HTTPException(status_code=409, detail=f"Cannot reverse purchase: only {available} units remain in stock for product {product_id}.")
            stock.quantity = available - quantity
            product.stock_qty = stock.quantity
            session.add(StockMovement(
                company_id=linked.company_id, branch_id=purchase.branch_id,
                warehouse_id=purchase.warehouse_id, product_id=product_id,
                quantity_delta=-quantity, reason="purchase_cancel",
                reference=purchase.purchase_number, created_by=membership["email"][:80],
            ))
        purchase.status = "cancelled"
        session.add(AuditLog(
            company_id=linked.company_id, username=membership["email"][:80],
            action="purchase_bill_cancelled", entity_type="Purchase",
            entity_id=str(purchase.id),
            details=json.dumps({"purchase_number": purchase.purchase_number, "stock_reversed": {str(k): str(v) for k, v in quantities.items()}}),
        ))
        session.commit()
        session.refresh(purchase)
        return _purchase_payload(purchase)
    except HTTPException:
        session.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Purchase bill cancellation could not be saved.") from exc


@app.get("/erp/customers", tags=["erp"])
def list_erp_customers(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    rows = session.scalars(select(Customer).where(
        Customer.company_id == linked.company_id
    ).order_by(Customer.name, Customer.id)).all()
    return {"items": [{
        "id": row.id, "name": row.name, "gstin": row.gstin,
        "state_code": row.state_code, "phone": row.phone,
        "email": row.email, "active": row.active,
    } for row in rows]}


@app.get("/erp/products", tags=["erp"])
def list_erp_products(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    rows = session.scalars(select(Product).where(
        Product.company_id == linked.company_id
    ).order_by(Product.name, Product.id)).all()
    return {"items": [{
        "id": row.id, "sku": row.sku, "name": row.name,
        "hsn_sac": row.hsn_sac, "unit": row.unit,
        "selling_price": str(row.selling_price),
        "purchase_price": str(row.purchase_price),
        "gst_rate": str(row.gst_rate), "active": row.active,
    } for row in rows]}


@app.get("/erp/suppliers", tags=["erp"])
def list_erp_suppliers(
    membership: dict = Depends(current_membership),
    session: Session = Depends(get_db),
):
    linked = _tenant_erp_context(session, membership["tenant_id"])
    rows = session.scalars(select(Supplier).where(
        Supplier.company_id == linked.company_id
    ).order_by(Supplier.name, Supplier.id)).all()
    return {"items": [{
        "id": row.id, "name": row.name, "gstin": row.gstin,
        "state_code": row.state_code, "phone": row.phone,
        "active": row.active,
    } for row in rows]}


@app.get("/auth/me", tags=["authentication"])
def me(membership: dict = Depends(current_membership)):
    return membership


_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
app.mount("/web-assets", StaticFiles(directory=str(_WEB_ROOT)), name="web-assets")


@app.get("/", include_in_schema=False)
def web_app():
    return FileResponse(_WEB_ROOT / "index.html")
