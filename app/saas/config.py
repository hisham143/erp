"""Runtime configuration for the cloud ERP API and desktop application."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = APP_DIR / "gst_billing.db"


def get_database_url() -> str:
    """Return the configured database URL, preserving the desktop SQLite default.

    Cloud deployments should set ERP_DATABASE_URL to a PostgreSQL URL, e.g.
    postgresql+psycopg://user:password@host:5432/database
    """
    configured = os.getenv("ERP_DATABASE_URL", "").strip()
    if configured:
        return configured
    return f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def engine_options(database_url: str) -> dict:
    """Return dialect-safe SQLAlchemy engine options."""
    options = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False}
    return options
