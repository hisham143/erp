"""Initial cloud API: health checks and tenant-scoped authentication."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import (
    SessionLocal, SaaSIdentity, SaaSRefreshSession, SaaSTenant,
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
    refresh_token: str = Field(min_length=40, max_length=200)


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
def register(payload: RegisterRequest, session: Session = Depends(get_db)):
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
def login(payload: LoginRequest, session: Session = Depends(get_db)):
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
        return result
    except RuntimeError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/auth/refresh", tags=["authentication"])
def refresh(payload: RefreshRequest, session: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
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
        return result
    except RuntimeError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@app.get("/auth/me", tags=["authentication"])
def me(membership: dict = Depends(current_membership)):
    return membership
