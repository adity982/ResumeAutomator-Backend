from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session
from urllib.parse import quote

from ..auth import get_current_user
from ..database import get_db
from ..deps import ensure_user
from ..portfolio_models import GitHubAuthorization, GitHubConnection
from ..schemas import AuthUser
from ..services import github_connection as github

router = APIRouter(prefix="/api/v1/connections/github", tags=["connections"])


class Callback(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    state: str = Field(min_length=32, max_length=128)


@router.get("")
def status(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    connection = db.get(GitHubConnection, auth.uid)
    return {"configured": github.configured(), "installation_url": "https://github.com/apps/" + quote(github.settings.github_app_slug, safe="") + "/installations/new" if github.configured() else None, "connected": bool(connection and connection.expires_at.replace(tzinfo=github.dt.timezone.utc) > github.now()), "login": connection.login if connection else None, "expires_at": connection.expires_at if connection else None}


@router.post("/start")
def start(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    return github.start(db, auth.uid)


@router.post("/complete")
def complete(payload: Callback, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    return github.finish(db, auth.uid, payload.code, payload.state)


@router.delete("", status_code=204)
def disconnect(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    db.execute(delete(GitHubConnection).where(GitHubConnection.user_uid == auth.uid))
    db.execute(delete(GitHubAuthorization).where(GitHubAuthorization.user_uid == auth.uid))
    db.commit()
    return Response(status_code=204)
