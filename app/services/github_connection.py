"""Read-only GitHub App user authorization. Credentials never reach the browser."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete

from ..config import settings
from ..portfolio_models import GitHubAuthorization, GitHubConnection


def now():
    return dt.datetime.now(dt.timezone.utc)


def configured():
    return bool(settings.github_client_id and settings.github_client_secret and settings.github_redirect_uri and settings.connection_encryption_key and settings.github_app_slug)


def cipher():
    if not configured():
        raise HTTPException(503, "GitHub connection is not configured by the operator yet. Public imports remain available.")
    uri = urlsplit(settings.github_redirect_uri)
    if uri.query or uri.fragment or not (uri.scheme == "https" or (settings.app_env != "production" and uri.scheme == "http" and uri.hostname in {"localhost", "127.0.0.1"})):
        raise HTTPException(503, "GitHub callback configuration is invalid.")
    try:
        return Fernet(settings.connection_encryption_key.encode())
    except ValueError as exc:
        raise HTTPException(503, "GitHub connection encryption configuration is invalid.") from exc


def api_get(path, token):
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            # Only internal constant/validated API paths are accepted by callers.
            with client.stream("GET", "https://api.github.com" + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}) as response:
                if response.status_code != 200:
                    raise HTTPException(409, "GitHub access is unavailable or revoked. Reconnect and check selected repositories.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 2_000_000:
                        raise HTTPException(502, "GitHub response exceeds the connection limit.")
                import json
                return json.loads(data)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "GitHub connection is unavailable. Retry shortly.") from exc


def start(db, uid):
    encryption = cipher()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    db.execute(delete(GitHubAuthorization).where((GitHubAuthorization.user_uid == uid) | (GitHubAuthorization.expires_at <= now())))
    db.add(GitHubAuthorization(state_hash=hashlib.sha256(state.encode()).hexdigest(), user_uid=uid, verifier_ciphertext=encryption.encrypt(verifier.encode()).decode(), expires_at=now() + dt.timedelta(minutes=10)))
    db.commit()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {"authorization_url": "https://github.com/login/oauth/authorize?" + urlencode({"client_id": settings.github_client_id, "redirect_uri": settings.github_redirect_uri, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})}


def finish(db, uid, code, state):
    encryption = cipher()
    # DELETE RETURNING makes state consumption single-use even with concurrent requests.
    authorization = db.execute(delete(GitHubAuthorization).where(GitHubAuthorization.state_hash == hashlib.sha256(state.encode()).hexdigest(), GitHubAuthorization.user_uid == uid, GitHubAuthorization.expires_at > now()).returning(GitHubAuthorization.verifier_ciphertext)).scalar_one_or_none()
    db.commit()
    if not authorization:
        raise HTTPException(409, "GitHub authorization expired, was already used, or belongs to another account. Connect again.")
    try:
        verifier = encryption.decrypt(authorization.encode()).decode()
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data={"client_id": settings.github_client_id, "client_secret": settings.github_client_secret, "redirect_uri": settings.github_redirect_uri, "code": code, "code_verifier": verifier})
            if response.status_code != 200 or len(response.content) > 16_000:
                raise ValueError("exchange failed")
            data = response.json()
        token = data.get("access_token", "")
        if not token or data.get("error") or not token.startswith("ghu_"):
            raise ValueError("GitHub App user token required")
        user = api_get("/user", token)
        login = str(user["login"])[:100]
        # Reconnect after at most eight hours; refresh tokens are deliberately not retained.
        expires = now() + dt.timedelta(seconds=max(1, min(int(data.get("expires_in", 28800)), 28800)))
        connection = db.get(GitHubConnection, uid)
        if connection is None:
            connection = GitHubConnection(user_uid=uid)
            db.add(connection)
        connection.login, connection.token_ciphertext, connection.expires_at = login, encryption.encrypt(token.encode()).decode(), expires
        db.commit()
        return {"connected": True, "login": login, "expires_at": expires}
    except (httpx.HTTPError, ValueError, KeyError, InvalidToken) as exc:
        raise HTTPException(502, "GitHub authorization could not be completed. Connect again.") from exc


def access_token(db, uid):
    connection = db.get(GitHubConnection, uid)
    if connection is None or connection.expires_at.replace(tzinfo=dt.timezone.utc) <= now():
        raise HTTPException(409, "Connect GitHub again before importing a private repository.")
    try:
        return cipher().decrypt(connection.token_ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(409, "Reconnect GitHub after the connection key changed.") from exc
