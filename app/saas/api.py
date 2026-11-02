"""Initial cloud API: health checks and tenant-scoped authentication."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
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
    SessionLocal, SaaSBusinessProfile, SaaSIdentity, SaaSRefreshSession, SaaSTenant,
    SaaSTenantMembership, hash_password, verify_password,
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
    return _business_profile_payload(profile)


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
        session.commit()
        session.refresh(profile)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Business setup could not be saved.") from exc
    return _business_profile_payload(profile)

@app.get("/auth/me", tags=["authentication"])
def me(membership: dict = Depends(current_membership)):
    return membership


_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
app.mount("/web-assets", StaticFiles(directory=str(_WEB_ROOT)), name="web-assets")


@app.get("/", include_in_schema=False)
def web_app():
    return FileResponse(_WEB_ROOT / "index.html")
