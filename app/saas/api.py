"""Initial health endpoints for the cloud ERP API.

Business endpoints will be added only after tenant authentication and
membership-scoped authorization are in place.
"""
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionLocal

app = FastAPI(
    title="ERP Cloud API",
    version="0.1.0",
    description="Multi-tenant ERP API foundation for the India SaaS product.",
)


@app.get("/health/live", tags=["health"])
def live():
    """Process liveness; does not depend on database availability."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready():
    """Readiness check verifies that the configured database is reachable."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is not ready.",
        ) from exc
    return {"status": "ready", "database": "reachable"}
