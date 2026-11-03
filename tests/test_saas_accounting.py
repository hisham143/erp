import pytest
from datetime import datetime
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.saas.api as api_module
from app.db import Base, SaaSTenantCompany, JournalEntry


@pytest.fixture
def accounting_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(api_module, "SessionLocal", sessions)
    monkeypatch.setenv("ERP_AUTH_SECRET", "accounting-test-secret-at-least-32-characters")
    with TestClient(api_module.app) as client:
        yield client
    engine.dispose()


def create_workspace(client, name, email):
    registered = client.post("/auth/register", json={
        "tenant_name": name,
        "owner_name": "Workspace Owner",
        "email": email,
        "password": "accounting-test-password-123",
    })
    assert registered.status_code == 201
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    onboarding = client.put("/onboarding/business", headers=headers, json={
        "trade_name": name,
        "legal_name": name,
        "gstin": "",
        "state_code": "32",
        "gst_registration_type": "unregistered",
        "financial_year_start_month": 4,
        "address": "Kerala",
        "phone": "",
        "first_branch_name": "Main Branch",
        "first_warehouse_name": "Main Warehouse",
    })
    assert onboarding.status_code == 200
    return headers


def test_accounting_chart_seeded_per_company_and_tenant_isolated(accounting_client):
    first = create_workspace(accounting_client, "First Books", "books-one@example.com")
    second = create_workspace(accounting_client, "Second Books", "books-two@example.com")

    first_chart = accounting_client.get("/erp/accounting/accounts", headers=first)
    second_chart = accounting_client.get("/erp/accounting/accounts", headers=second)
    assert first_chart.status_code == 200
    assert second_chart.status_code == 200
    assert len(first_chart.json()["items"]) >= 15
    assert len(second_chart.json()["items"]) == len(first_chart.json()["items"])
    assert {row["id"] for row in first_chart.json()["items"]}.isdisjoint(
        {row["id"] for row in second_chart.json()["items"]}
    )


def test_manual_journal_posts_balanced_entry_and_reports(accounting_client):
    headers = create_workspace(accounting_client, "Journal Books", "journal@example.com")
    chart = accounting_client.get("/erp/accounting/accounts", headers=headers).json()["items"]
    by_code = {row["code"]: row for row in chart}
    response = accounting_client.post("/erp/accounting/journals", headers=headers, json={
        "entry_date": "2026-11-01",
        "narration": "Initial owner capital",
        "lines": [
            {"account_id": by_code["1000"]["id"], "description": "Cash received", "debit": "1000.00", "credit": "0"},
            {"account_id": by_code["3000"]["id"], "description": "Capital introduced", "debit": "0", "credit": "1000.00"},
        ],
    })
    assert response.status_code == 201
    assert response.json()["total_debit"] == "1000.00"
    assert response.json()["total_credit"] == "1000.00"

    trial = accounting_client.get("/erp/accounting/trial-balance", headers=headers)
    assert trial.status_code == 200
    assert trial.json()["balanced"] is True
    assert trial.json()["total_debit"] == "1000.00"
    assert trial.json()["total_credit"] == "1000.00"

    ledger = accounting_client.get(
        f"/erp/accounting/ledger/{by_code['1000']['id']}?from_date=2026-11-01&to_date=2026-11-30",
        headers=headers,
    )
    assert ledger.status_code == 200
    assert len(ledger.json()["items"]) == 1
    assert ledger.json()["closing_balance"] == "1000.00"


def test_manual_journal_rejects_unbalanced_or_foreign_account(accounting_client):
    first = create_workspace(accounting_client, "Journal One", "journal-one@example.com")
    second = create_workspace(accounting_client, "Journal Two", "journal-two@example.com")
    first_accounts = accounting_client.get("/erp/accounting/accounts", headers=first).json()["items"]
    second_accounts = accounting_client.get("/erp/accounting/accounts", headers=second).json()["items"]
    cash = next(row for row in first_accounts if row["code"] == "1000")
    capital = next(row for row in first_accounts if row["code"] == "3000")
    foreign_cash = next(row for row in second_accounts if row["code"] == "1000")

    unbalanced = accounting_client.post("/erp/accounting/journals", headers=first, json={
        "narration": "Should fail",
        "lines": [
            {"account_id": cash["id"], "debit": "100.00", "credit": "0"},
            {"account_id": capital["id"], "debit": "0", "credit": "90.00"},
        ],
    })
    assert unbalanced.status_code == 422

    foreign = accounting_client.post("/erp/accounting/journals", headers=first, json={
        "narration": "Foreign account",
        "lines": [
            {"account_id": foreign_cash["id"], "debit": "100.00", "credit": "0"},
            {"account_id": capital["id"], "debit": "0", "credit": "100.00"},
        ],
    })
    assert foreign.status_code == 404


def test_owner_cannot_demote_themselves(accounting_client):
    headers = create_workspace(accounting_client, "Sales User Books", "sales-user@example.com")
    me = accounting_client.get("/auth/me", headers=headers).json()
    changed = accounting_client.patch(
        f"/workspace/members/{me['user_id']}/role",
        headers=headers, json={"role": "sales"},
    )
    assert changed.status_code == 409  # The sole workspace owner cannot demote themselves.



def test_source_journal_is_idempotent_and_reversible(accounting_client):
    headers = create_workspace(accounting_client, "Auto Posting Books", "auto-post@example.com")
    with api_module.SessionLocal() as session:
        me = accounting_client.get("/auth/me", headers=headers).json()
        linked = session.scalar(
            __import__("sqlalchemy").select(SaaSTenantCompany).where(
                SaaSTenantCompany.tenant_id == me["tenant_id"]
            )
        )
        membership = {"email": me["email"]}
        original = api_module._post_source_journal(
            session, linked, membership, "sales_invoice", "INV-1",
            datetime(2026, 11, 3), "Test sales invoice",
            [
                ("1100", "Accounts receivable", Decimal("118.00"), Decimal("0")),
                ("4000", "Sales revenue", Decimal("0"), Decimal("100.00")),
                ("2100", "Output CGST", Decimal("0"), Decimal("9.00")),
                ("2110", "Output SGST", Decimal("0"), Decimal("9.00")),
            ],
        )
        session.flush()
        same = api_module._post_source_journal(
            session, linked, membership, "sales_invoice", "INV-1",
            datetime(2026, 11, 3), "Duplicate should be ignored",
            [
                ("1100", "Accounts receivable", Decimal("118.00"), Decimal("0")),
                ("4000", "Sales revenue", Decimal("0"), Decimal("100.00")),
                ("2100", "Output CGST", Decimal("0"), Decimal("9.00")),
                ("2110", "Output SGST", Decimal("0"), Decimal("9.00")),
            ],
        )
        assert same.id == original.id
        reversal = api_module._reverse_source_journal(
            session, linked, membership, "sales_invoice", "INV-1",
            "sales_invoice_cancel", datetime(2026, 11, 4), "Cancel invoice",
        )
        session.commit()
        assert reversal is not None
        entries = session.scalars(
            __import__("sqlalchemy").select(JournalEntry).where(
                JournalEntry.company_id == linked.company_id
            )
        ).all()
        assert len(entries) == 2
        assert sum((Decimal(line.debit) for line in reversal.lines), Decimal("0")) == Decimal("118.00")
        assert sum((Decimal(line.credit) for line in reversal.lines), Decimal("0")) == Decimal("118.00")
