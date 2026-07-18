from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from ..database import SessionLocal
from ..middleware import api_metrics


router = APIRouter(tags=["health"])


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is not ready.") from exc
    return {"status": "ready", "database": "ok"}


@router.get("/metrics")
def metrics():
    return api_metrics.snapshot()
