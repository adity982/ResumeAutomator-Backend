from __future__ import annotations

import datetime as dt
import hashlib
import time

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..config import settings
from ..database import SessionLocal
from ..portfolio_models import UsageWindow


def consume(uid: str, path: str, method: str):
    now = dt.datetime.now(dt.timezone.utc)
    expensive = (method == "POST" and (path.endswith(("/preview", "/import", "/projects")) or "/ai/" in path)) or (method == "PATCH" and "/project-evidence/" in path)
    windows = [(60, settings.rate_limit_per_minute, "all")]
    if expensive:
        windows.extend([(60, 10, "expensive"), (86400, 200, "expensive")])
    with SessionLocal() as db:
        db.query(UsageWindow).filter(UsageWindow.expires_at < now).delete()
        insert = postgres_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        for seconds, limit, operation in windows:
            bucket = int(time.time()) // seconds
            key = hashlib.sha256(f"{uid}:{operation}:{seconds}:{bucket}".encode()).hexdigest()
            statement = insert(UsageWindow).values(key=key, count=1, expires_at=dt.datetime.fromtimestamp((bucket + 1) * seconds, dt.timezone.utc))
            statement = statement.on_conflict_do_update(index_elements=[UsageWindow.key], set_={"count": UsageWindow.count + 1}, where=UsageWindow.count < limit).returning(UsageWindow.count)
            if db.execute(statement).scalar_one_or_none() is None:
                db.rollback()
                raise HTTPException(429, "Your usage limit for this operation was reached. Try again after the current window.", headers={"Retry-After": str(seconds)})
        db.commit()
