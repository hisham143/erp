"""Real-browser onboarding journey. Installed in CI via requirements-ui-test.txt."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


@pytest.fixture
def running_web_app(tmp_path):
    database = tmp_path / "web_e2e.db"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    env = os.environ.copy()
    env["ERP_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["ERP_AUTH_SECRET"] = "playwright-test-secret-with-more-than-32-characters"
    env["PYTHONPATH"] = os.getcwd()

    startup = (
        "from app.db import Base, engine; "
        "Base.metadata.create_all(bind=engine); "
        "import uvicorn; "
        f"uvicorn.run('app.saas.api:app', host='127.0.0.1', port={port}, log_level='error')"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", startup],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 25
    ready = False
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("ERP Cloud test server exited before becoming ready.")
        try:
            with urllib.request.urlopen(base_url + "/health/live", timeout=1) as response:
                ready = response.status == 200
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    if not ready:
        process.terminate()
        raise RuntimeError("ERP Cloud test server did not become ready.")
    try:
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_owner_can_register_onboard_and_sign_in_again(running_web_app):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(running_web_app, wait_until="networkidle")

        page.locator("#register-tab").click()
        page.locator('#register-form input[name="tenant_name"]').fill("Playwright Wholesale")
        page.locator('#register-form input[name="owner_name"]').fill("Test Owner")
        page.locator('#register-form input[name="email"]').fill("owner@playwright.test")
        page.locator('#register-form input[name="password"]').fill("Strong-Password-123")
        page.locator('#register-form button[type="submit"]').click()
        page.locator("#onboarding-view").wait_for(state="visible")

        page.locator('input[name="trade_name"]').fill("Playwright Traders")
        page.locator('input[name="legal_name"]').fill("Playwright Traders LLP")
        page.locator('select[name="gst_registration_type"]').select_option("regular")
        page.locator('input[name="gstin"]').fill("32ABCDE1234F1Z5")
        page.locator('select[name="state_code"]').select_option("32")
        page.locator('input[name="phone"]').fill("+919876543210")
        page.locator("#business-form button[type='submit']").click()
        page.locator("#complete-view").wait_for(state="visible")
        assert "Playwright Traders" in page.locator("#complete-summary").inner_text()

        workspace_code = page.locator(".detail-cell").filter(
            has_text="Workspace code"
        ).locator("strong").inner_text()
        assert workspace_code.startswith("playwright-wholesale-")

        # A hard reload clears in-memory tokens; the owner must authenticate again.
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("getComputedStyle(document.querySelector('.app-frame')).display") == "block"
        page.reload(wait_until="networkidle")
        page.locator("#login-form").wait_for(state="visible")
        page.locator('#login-form input[name="email"]').fill("owner@playwright.test")
        page.locator('#login-form input[name="password"]').fill("Strong-Password-123")
        page.locator('#login-form input[name="tenant_slug"]').fill(workspace_code)
        page.locator('#login-form button[type="submit"]').click()
        page.locator("#complete-view").wait_for(state="visible")
        assert "Playwright Traders" in page.locator("#complete-summary").inner_text()
        assert page.evaluate("getComputedStyle(document.querySelector('.app-frame')).display") == "block"
        page.set_viewport_size({"width": 768, "height": 1024})
        assert page.evaluate("getComputedStyle(document.querySelector('.app-frame')).display") == "grid"
        assert page.locator("body").inner_text().count("Business profile saved") == 0
        browser.close()
