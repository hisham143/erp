import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.saas.api as api_module
from app.db import (
    Base, SaaSIdentity, SaaSTenant, SaaSTenantMembership,
    SaaSRefreshSession,
)
from app.saas.security import create_access_token, decode_access_token


@pytest.fixture
def client_and_sessions(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(api_module, "SessionLocal", sessions)
    monkeypatch.setenv("ERP_AUTH_SECRET", "test-secret-that-is-at-least-32-characters-long")
    with TestClient(api_module.app) as client:
        yield client, sessions
    engine.dispose()


def test_register_creates_isolated_tenant_owner_and_tokens(client_and_sessions):
    client, sessions = client_and_sessions
    response = client.post("/auth/register", json={
        "tenant_name": "Acme Wholesale",
        "owner_name": "Account Owner",
        "email": "OWNER@EXAMPLE.COM",
        "password": "a-strong-password-123",
    })
    assert response.status_code == 201
    payload = response.json()
    assert payload["tenant"]["name"] == "Acme Wholesale"
    assert payload["user"]["email"] == "owner@example.com"
    assert payload["access_token"]
    assert payload["refresh_token"]

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["tenant_id"] == payload["tenant"]["id"]
    assert me.json()["role"] == "owner"

    with sessions() as session:
        assert session.scalar(select(SaaSTenant).where(
            SaaSTenant.id == payload["tenant"]["id"]
        )) is not None
        assert session.scalar(select(SaaSIdentity).where(
            SaaSIdentity.email == "owner@example.com"
        )) is not None
        assert session.scalar(select(SaaSTenantMembership).where(
            SaaSTenantMembership.tenant_id == payload["tenant"]["id"]
        )) is not None
        assert session.scalar(select(SaaSRefreshSession)) is not None


def test_registration_rejects_duplicate_email(client_and_sessions):
    client, _ = client_and_sessions
    body = {
        "tenant_name": "First Workspace",
        "owner_name": "Account Owner",
        "email": "same@example.com",
        "password": "a-strong-password-123",
    }
    assert client.post("/auth/register", json=body).status_code == 201
    duplicate = {**body, "tenant_name": "Second Workspace"}
    assert client.post("/auth/register", json=duplicate).status_code == 409


def test_login_requires_active_tenant_membership(client_and_sessions):
    client, _ = client_and_sessions
    registration = client.post("/auth/register", json={
        "tenant_name": "Login Workspace",
        "owner_name": "Account Owner",
        "email": "login@example.com",
        "password": "a-strong-password-123",
    }).json()
    response = client.post("/auth/login", json={
        "email": "LOGIN@example.com",
        "password": "a-strong-password-123",
        "tenant_slug": registration["tenant"]["slug"],
    })
    assert response.status_code == 200
    invalid = client.post("/auth/login", json={
        "email": "login@example.com",
        "password": "wrong-password",
        "tenant_slug": registration["tenant"]["slug"],
    })
    assert invalid.status_code == 401


def test_refresh_token_rotates_and_old_token_cannot_be_reused(client_and_sessions):
    client, _ = client_and_sessions
    registered = client.post("/auth/register", json={
        "tenant_name": "Refresh Workspace",
        "owner_name": "Account Owner",
        "email": "refresh@example.com",
        "password": "a-strong-password-123",
    }).json()
    first = client.post("/auth/refresh", json={
        "refresh_token": registered["refresh_token"]
    })
    assert first.status_code == 200
    assert first.json()["refresh_token"] != registered["refresh_token"]
    replay = client.post("/auth/refresh", json={
        "refresh_token": registered["refresh_token"]
    })
    assert replay.status_code == 401


def test_access_token_rejects_modified_signature(monkeypatch):
    monkeypatch.setenv("ERP_AUTH_SECRET", "test-secret-that-is-at-least-32-characters-long")
    token = create_access_token(1, 1)
    assert decode_access_token(token)["tid"] == 1
    altered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(ValueError):
        decode_access_token(altered)


def test_protected_endpoint_rejects_missing_token(client_and_sessions):
    client, _ = client_and_sessions
    response = client.get("/auth/me")
    assert response.status_code == 401
