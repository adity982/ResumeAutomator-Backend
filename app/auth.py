from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .config import settings
from .schemas import AuthUser


bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    token = credentials.credentials
    if settings.auth_mode == "development":
        if settings.app_env == "production" or not token.startswith("dev:"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid development token.")
        parts = token.split(":", 2)
        if len(parts) != 3 or not parts[1] or "@" not in parts[2]:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed development token.")
        return AuthUser(uid=parts[1][:128], email=parts[2][:320])

    try:
        payload = id_token.verify_firebase_token(
            token,
            google_requests.Request(),
            audience=settings.firebase_project_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired identity token.") from exc

    uid = payload.get("sub") or payload.get("user_id")
    email = payload.get("email")
    if not uid or not email or payload.get("email_verified") is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verified email identity required.")
    return AuthUser(uid=str(uid)[:128], email=str(email)[:320])
