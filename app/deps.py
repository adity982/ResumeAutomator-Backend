from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models
from .schemas import AuthUser


def ensure_user(db: Session, auth: AuthUser) -> models.User:
    user = db.get(models.User, auth.uid)
    if user is None:
        user = models.User(uid=auth.uid, email=auth.email)
        db.add(user)
        db.flush()
    elif user.email != auth.email:
        user.email = auth.email
        db.flush()
    return user


def owned(db: Session, model, resource_id: int, auth: AuthUser):
    item = db.query(model).filter(model.id == resource_id, model.user_uid == auth.uid).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return item


def verify_optional_owner(db: Session, model, resource_id: int | None, auth: AuthUser) -> None:
    if resource_id is not None:
        owned(db, model, resource_id, auth)
