import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.saas.api as api_module
from app.db import (
    Base, SaaSIdentity, SaaSTenant, SaaSTenantMembership,
    SaaSRefreshSession, Company, Branch, Warehouse, BusinessSettings, SaaSTenantCompany,
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


def _register(client, email, tenant_name):
    response = client.post("/auth/register", json={
        "tenant_name": tenant_name,
        "owner_name": "Workspace Owner",
        "email": email,
        "password": "a-strong-password-123",
    })
    assert response.status_code == 201
    return response.json()


def test_business_onboarding_save_and_read_is_tenant_scoped(client_and_sessions):
    client, _ = client_and_sessions
    first = _register(client, "owner-one@example.com", "First Workspace")
    second = _register(client, "owner-two@example.com", "Second Workspace")
    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}

    missing = client.get("/onboarding/business", headers=first_headers)
    assert missing.status_code == 404

    payload = {
        "trade_name": "Acme Wholesale",
        "legal_name": "Acme Wholesale Private Limited",
        "gstin": "32ABCDE1234F1Z5",
        "state_code": "32",
        "gst_registration_type": "regular",
        "financial_year_start_month": 4,
        "address": "Kochi, Kerala",
        "phone": "+919876543210",
        "first_branch_name": "Kochi Branch",
        "first_warehouse_name": "Central Warehouse",
    }
    saved = client.put("/onboarding/business", json=payload, headers=first_headers)
    assert saved.status_code == 200
    assert saved.json()["onboarding_completed"] is True
    assert saved.json()["trade_name"] == "Acme Wholesale"

    read_back = client.get("/onboarding/business", headers=first_headers)
    assert read_back.status_code == 200
    assert read_back.json()["gstin"] == "32ABCDE1234F1Z5"
    assert read_back.json()["erp_setup"]["company"]["name"] == "Acme Wholesale"
    assert read_back.json()["erp_setup"]["branch"]["name"] == "Kochi Branch"
    assert read_back.json()["erp_setup"]["warehouse"]["name"] == "Central Warehouse"

    other_tenant = client.get("/onboarding/business", headers=second_headers)
    assert other_tenant.status_code == 404


def test_business_onboarding_rejects_invalid_gstin_and_state_mismatch(client_and_sessions):
    client, _ = client_and_sessions
    registered = _register(client, "gst-check@example.com", "GST Check Workspace")
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    payload = {
        "trade_name": "GST Check Traders",
        "gstin": "INVALID",
        "state_code": "32",
        "gst_registration_type": "regular",
        "first_branch_name": "Main Branch",
        "first_warehouse_name": "Main Warehouse",
    }
    invalid_format = client.put("/onboarding/business", json=payload, headers=headers)
    assert invalid_format.status_code == 422

    payload["gstin"] = "29ABCDE1234F1Z5"
    mismatch = client.put("/onboarding/business", json=payload, headers=headers)
    assert mismatch.status_code == 422


def test_business_onboarding_allows_unregistered_business(client_and_sessions):
    client, _ = client_and_sessions
    registered = _register(client, "unregistered@example.com", "Unregistered Workspace")
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    response = client.put("/onboarding/business", json={
        "trade_name": "Local Retail Shop",
        "state_code": "32",
        "gst_registration_type": "unregistered",
        "first_branch_name": "Main Branch",
        "first_warehouse_name": "Main Warehouse",
    }, headers=headers)
    assert response.status_code == 200
    assert response.json()["gstin"] == ""
    assert response.json()["onboarding_completed"] is True


def test_web_app_serves_ui_and_assets(client_and_sessions):
    client, _ = client_and_sessions
    page = client.get("/")
    assert page.status_code == 200
    assert "ERP Cloud" in page.text
    assert "Create your workspace" in page.text
    css = client.get("/web-assets/app.css")
    js = client.get("/web-assets/app.js")
    assert css.status_code == 200 and ".app-frame" in css.text
    assert js.status_code == 200 and "/onboarding/business" in js.text


def test_logout_revokes_refresh_token(client_and_sessions):
    client, _ = client_and_sessions
    registered = _register(client, "logout@example.com", "Logout Workspace")
    response = client.post("/auth/logout", json={
        "refresh_token": registered["refresh_token"]
    })
    assert response.status_code == 200
    assert response.json()["status"] == "signed_out"
    replay = client.post("/auth/refresh", json={
        "refresh_token": registered["refresh_token"]
    })
    assert replay.status_code == 401


def test_auth_issues_http_only_refresh_cookie_and_logout_clears_it(client_and_sessions):
    client, _ = client_and_sessions
    registered = _register(client, "cookie-session@example.com", "Cookie Session Workspace")
    cookie = client.cookies.get("erp_refresh")
    assert cookie == registered["refresh_token"]
    set_cookie = client.cookies.jar
    assert any(
        item.name == "erp_refresh" and item.has_nonstandard_attr("HttpOnly")
        for item in set_cookie
    )

    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get("erp_refresh") == refreshed.json()["refresh_token"]
    assert client.cookies.get("erp_refresh") != registered["refresh_token"]

    signed_out = client.post("/auth/logout")
    assert signed_out.status_code == 200
    assert client.cookies.get("erp_refresh") is None


def test_business_onboarding_creates_operational_erp_hierarchy_once_and_tenant_scoped(client_and_sessions):
    client, sessions = client_and_sessions
    first = _register(client, "erp-owner-one@example.com", "ERP Workspace One")
    second = _register(client, "erp-owner-two@example.com", "ERP Workspace Two")
    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    payload = {
        "trade_name": "Northstar Wholesale",
        "legal_name": "Northstar Wholesale LLP",
        "gstin": "",
        "state_code": "32",
        "gst_registration_type": "unregistered",
        "financial_year_start_month": 4,
        "address": "Kochi, Kerala",
        "phone": "+919876543210",
        "first_branch_name": "Kochi Branch",
        "first_warehouse_name": "Central Warehouse",
    }

    saved = client.put("/onboarding/business", json=payload, headers=first_headers)
    assert saved.status_code == 200
    setup = saved.json()["erp_setup"]
    assert setup["company"]["name"] == "Northstar Wholesale"
    assert setup["branch"]["name"] == "Kochi Branch"
    assert setup["warehouse"]["name"] == "Central Warehouse"
    setup_read = client.get("/onboarding/erp-setup", headers=first_headers)
    assert setup_read.status_code == 200
    assert setup_read.json() == setup

    # Editing the profile updates the linked master records; it must not duplicate them.
    payload["trade_name"] = "Northstar Wholesale Updated"
    updated = client.put("/onboarding/business", json=payload, headers=first_headers)
    assert updated.status_code == 200
    assert updated.json()["erp_setup"]["company"]["id"] == setup["company"]["id"]

    with sessions() as session:
        assert len(session.scalars(select(Company)).all()) == 1
        assert len(session.scalars(select(Branch)).all()) == 1
        assert len(session.scalars(select(Warehouse)).all()) == 1
        assert len(session.scalars(select(BusinessSettings)).all()) == 1
        assert len(session.scalars(select(SaaSTenantCompany)).all()) == 1
        assert session.get(Company, setup["company"]["id"]).name == "Northstar Wholesale Updated"

    # A second tenant cannot see the first tenant's operational company mapping.
    assert client.get("/onboarding/erp-setup", headers=second_headers).status_code == 404
    second_saved = client.put("/onboarding/business", json=payload, headers=second_headers)
    assert second_saved.status_code == 200
    assert second_saved.json()["erp_setup"]["company"]["id"] != setup["company"]["id"]


def _save_unregistered_profile(client, token, trade_name):
    headers = {"Authorization": f"Bearer {token}"}
    response = client.put("/onboarding/business", headers=headers, json={
        "trade_name": trade_name,
        "state_code": "32",
        "gst_registration_type": "unregistered",
        "first_branch_name": "Main Branch",
        "first_warehouse_name": "Main Warehouse",
    })
    assert response.status_code == 200
    return response.json()["erp_setup"]


def test_erp_master_read_apis_are_company_and_tenant_scoped(client_and_sessions):
    from app.db import Customer, Product, Supplier
    client, sessions = client_and_sessions
    first = _register(client, "scope-one@example.com", "Scope Workspace One")
    second = _register(client, "scope-two@example.com", "Scope Workspace Two")
    first_setup = _save_unregistered_profile(client, first["access_token"], "First Company")
    second_setup = _save_unregistered_profile(client, second["access_token"], "Second Company")

    with sessions() as session:
        session.add_all([
            Customer(company_id=first_setup["company"]["id"], name="First Customer"),
            Customer(company_id=second_setup["company"]["id"], name="Second Customer"),
            Product(company_id=first_setup["company"]["id"], sku="FIRST-SKU", name="First Product"),
            Product(company_id=second_setup["company"]["id"], sku="SECOND-SKU", name="Second Product"),
            Supplier(company_id=first_setup["company"]["id"], name="First Supplier"),
            Supplier(company_id=second_setup["company"]["id"], name="Second Supplier"),
        ])
        session.commit()

    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    assert client.get("/erp/context", headers=first_headers).json()["company"]["id"] == first_setup["company"]["id"]
    for endpoint, expected in [
        ("/erp/customers", "First Customer"),
        ("/erp/products", "First Product"),
        ("/erp/suppliers", "First Supplier"),
    ]:
        response = client.get(endpoint, headers=first_headers)
        assert response.status_code == 200
        names = [item.get("name") for item in response.json()["items"]]
        assert expected in names
        assert not any(name and name.startswith("Second ") for name in names)

    for endpoint in ["/erp/context", "/erp/customers", "/erp/products", "/erp/suppliers"]:
        response = client.get(endpoint, headers=second_headers)
        assert response.status_code == 200
        body = response.json()
        if endpoint == "/erp/context":
            assert body["company"]["id"] == second_setup["company"]["id"]
        else:
            assert not any(item.get("name", "").startswith("First ") for item in body["items"])


def test_workspace_member_roles_are_owner_managed_and_tenant_scoped(client_and_sessions):
    client, sessions = client_and_sessions
    owner = _register(client, "role-owner@example.com", "Role Workspace")
    other = _register(client, "role-other@example.com", "Other Role Workspace")
    with sessions() as session:
        staff = SaaSIdentity(
            email="staff-role@example.com",
            full_name="Workspace Staff",
            password_hash="unused-test-hash",
            active=True,
        )
        session.add(staff)
        session.flush()
        staff_id = staff.id
        session.add(SaaSTenantMembership(
            tenant_id=owner["tenant"]["id"], identity_id=staff.id,
            role="staff", active=True,
        ))
        session.commit()

    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    listed = client.get("/workspace/members", headers=owner_headers)
    assert listed.status_code == 200
    assert any(item["identity_id"] == staff_id for item in listed.json()["items"])

    changed = client.patch(
        f"/workspace/members/{staff_id}/role",
        json={"role": "sales"}, headers=owner_headers,
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "sales"

    assert client.patch(
        f"/workspace/members/{staff_id}/role",
        json={"role": "admin"}, headers=other_headers,
    ).status_code == 404

    with sessions() as session:
        owner_membership = session.scalar(select(SaaSTenantMembership).where(
            SaaSTenantMembership.tenant_id == owner["tenant"]["id"],
            SaaSTenantMembership.identity_id == owner["user"]["id"],
        ))
        owner_membership.role = "staff"
        session.commit()
    forbidden = client.get("/workspace/members", headers=owner_headers)
    assert forbidden.status_code == 403



def test_sales_invoice_api_calculates_gst_and_scopes_records_to_tenant(client_and_sessions):
    from decimal import Decimal
    from app.db import Customer, Product, Invoice, InvoiceItem

    client, sessions = client_and_sessions
    first = _register(client, "sales-one@example.com", "Sales Workspace One")
    second = _register(client, "sales-two@example.com", "Sales Workspace Two")
    first_setup = _save_unregistered_profile(client, first["access_token"], "Sales Company One")
    second_setup = _save_unregistered_profile(client, second["access_token"], "Sales Company Two")
    with sessions() as session:
        first_customer = Customer(
            company_id=first_setup["company"]["id"], name="Local Buyer",
            state_code="32", active=True,
        )
        second_customer = Customer(
            company_id=second_setup["company"]["id"], name="Other Buyer",
            state_code="32", active=True,
        )
        first_product = Product(
            company_id=first_setup["company"]["id"], sku="SALE-ONE",
            name="Widget", selling_price=Decimal("100.00"),
            gst_rate=Decimal("18.00"), active=True,
        )
        session.add_all([first_customer, second_customer, first_product])
        session.commit()
        first_customer_id = first_customer.id
        second_customer_id = second_customer.id
        first_product_id = first_product.id

    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    created = client.post("/erp/sales/invoices", headers=first_headers, json={
        "customer_id": first_customer_id,
        "invoice_date": "2026-11-03",
        "items": [{"product_id": first_product_id, "quantity": "2", "unit_price": "100"}],
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["invoice_number"].startswith("INV-")
    assert body["taxable_total"] == "200.00"
    assert body["cgst_total"] == "18.00"
    assert body["sgst_total"] == "18.00"
    assert body["igst_total"] == "0.00"
    assert body["grand_total"] == "236.00"
    assert body["items"][0]["line_total"] == "236.00"

    invoice_id = body["id"]
    assert client.get(f"/erp/sales/invoices/{invoice_id}", headers=first_headers).status_code == 200
    assert client.get(f"/erp/sales/invoices/{invoice_id}", headers=second_headers).status_code == 404
    foreign_customer = client.post("/erp/sales/invoices", headers=first_headers, json={
        "customer_id": second_customer_id,
        "items": [{"product_id": first_product_id, "quantity": "1"}],
    })
    assert foreign_customer.status_code == 404
    assert client.get("/erp/sales/invoices", headers=second_headers).json()["items"] == []

    with sessions() as session:
        saved = session.get(Invoice, invoice_id)
        assert saved is not None
        assert len(saved.items) == 1
        assert saved.items[0].description_snapshot == "Widget"


def test_sales_invoice_rejects_invalid_lines_without_partial_records(client_and_sessions):
    from app.db import Customer, Product, Invoice
    client, sessions = client_and_sessions
    owner = _register(client, "sales-invalid@example.com", "Sales Invalid Workspace")
    setup = _save_unregistered_profile(client, owner["access_token"], "Sales Invalid Company")
    with sessions() as session:
        customer = Customer(company_id=setup["company"]["id"], name="Buyer", state_code="32")
        product = Product(
            company_id=setup["company"]["id"], sku="SALE-INVALID",
            name="Test Product", selling_price=Decimal("50.00"),
            gst_rate=Decimal("18.00"),
        )
        session.add_all([customer, product])
        session.commit()
        customer_id, product_id = customer.id, product.id

    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    response = client.post("/erp/sales/invoices", headers=headers, json={
        "customer_id": customer_id,
        "items": [{"product_id": product_id, "quantity": "1", "discount_amount": "60"}],
    })
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalar(select(Invoice)) is None


def test_sales_invoice_requires_sales_permission_and_authentication(client_and_sessions):
    client, sessions = client_and_sessions
    owner = _register(client, "sales-permission@example.com", "Sales Permission Workspace")
    setup = _save_unregistered_profile(client, owner["access_token"], "Sales Permission Company")
    with sessions() as session:
        customer = Customer(company_id=setup["company"]["id"], name="Buyer", state_code="32")
        product = Product(
            company_id=setup["company"]["id"], sku="SALE-PERMISSION",
            name="Test Product", selling_price=Decimal("10.00"),
            gst_rate=Decimal("0.00"),
        )
        staff = SaaSIdentity(
            email="sales-readonly@example.com", full_name="Read Only",
            password_hash="unused-test-hash", active=True,
        )
        session.add_all([customer, product, staff])
        session.flush()
        session.add(SaaSTenantMembership(
            tenant_id=owner["tenant"]["id"], identity_id=staff.id,
            role="staff", active=True,
        ))
        staff_token = create_access_token(staff.id, owner["tenant"]["id"])
        customer_id, product_id = customer.id, product.id
        session.commit()

    payload = {"customer_id": customer_id, "items": [{"product_id": product_id, "quantity": "1"}]}
    assert client.post("/erp/sales/invoices", json=payload).status_code == 401
    denied = client.post("/erp/sales/invoices", headers={
        "Authorization": f"Bearer {staff_token}"
    }, json=payload)
    assert denied.status_code == 403
