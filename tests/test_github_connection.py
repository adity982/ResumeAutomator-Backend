import datetime as dt
import base64
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from app import models
from app.database import SessionLocal
from app.services import github_connection as github, github_import

OTHER = {"Authorization": "Bearer dev:other:other@example.com"}
TOKEN = "ghu_" + "x" * 40


@pytest.fixture
def configured(monkeypatch):
    values = {"github_client_id": "test-app", "github_client_secret": "test-secret", "github_redirect_uri": "https://example.com/", "github_app_slug": "resume-test", "connection_encryption_key": Fernet.generate_key().decode()}
    monkeypatch.setattr(github, "settings", replace(github.settings, **values))


def mock_exchange(monkeypatch):
    real_client = httpx.Client
    def handler(request):
        if request.url.host == "github.com":
            assert b"code_verifier=" in request.content
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 28800})
        assert request.headers["authorization"] == "Bearer " + TOKEN
        return httpx.Response(200, json={"login": "example"})
    monkeypatch.setattr(github.httpx, "Client", lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))


def test_pkce_owner_binding_encryption_replay_and_disconnect(client, auth_headers, configured, monkeypatch):
    started = client.post("/api/v1/connections/github/start", headers=auth_headers)
    assert started.status_code == 200
    params = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    assert len(params["code_challenge"][0]) == 43 and params["code_challenge_method"] == ["S256"]
    assert "scope" not in params
    payload = {"code": "test-code", "state": params["state"][0]}
    assert client.post("/api/v1/connections/github/complete", headers=OTHER, json=payload).status_code == 409
    mock_exchange(monkeypatch)
    completed = client.post("/api/v1/connections/github/complete", headers=auth_headers, json=payload)
    assert completed.status_code == 200 and TOKEN not in completed.text
    assert client.post("/api/v1/connections/github/complete", headers=auth_headers, json=payload).status_code == 409
    with SessionLocal() as db:
        connection = db.get(models.GitHubConnection, "user-1")
        assert TOKEN not in connection.token_ciphertext
        assert github.access_token(db, "user-1") == TOKEN
    assert client.get("/api/v1/connections/github", headers=OTHER).json()["connected"] is False
    exported = client.get("/api/v1/account/export", headers=auth_headers)
    assert TOKEN not in exported.text and "token_ciphertext" not in exported.text
    assert client.delete("/api/v1/connections/github", headers=auth_headers).status_code == 204
    assert client.post("/api/v1/sources/preview", headers=auth_headers, json={"url": "https://github.com/me/private", "use_connected_github": True}).status_code == 409


def test_expired_state_and_account_deletion(client, auth_headers, configured):
    start = client.post("/api/v1/connections/github/start", headers=auth_headers).json()
    state = parse_qs(urlsplit(start["authorization_url"]).query)["state"][0]
    with SessionLocal() as db:
        db.query(models.GitHubAuthorization).one().expires_at = github.now() - dt.timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/connections/github/complete", headers=auth_headers, json={"state": state, "code": "expired"}).status_code == 409
    client.delete("/api/v1/account", headers=auth_headers)
    with SessionLocal() as db:
        assert db.query(models.GitHubAuthorization).count() == 0


def test_connected_preview_uses_owner_token_and_labels_private(client, auth_headers, configured, monkeypatch):
    client.post("/api/v1/connections/github/start", headers=auth_headers)
    with SessionLocal() as db:
        db.add(models.GitHubConnection(user_uid="user-1", login="example", token_ciphertext=github.cipher().encrypt(TOKEN.encode()).decode(), expires_at=github.now() + dt.timedelta(hours=1)))
        db.commit()
    def preview(url, token):
        assert token == TOKEN
        return {"repository": "me/private", "commit_sha": "a" * 40, "source_url": url, "description": "Private", "is_private": True, "is_fork": False, "files": []}
    monkeypatch.setattr(github_import, "connected_preview", preview)
    result = client.post("/api/v1/sources/preview", headers=auth_headers, json={"url": "https://github.com/me/private", "use_connected_github": True})
    assert result.status_code == 201 and result.json()["is_private"] is True
    assert client.get("/api/v1/sources", headers=OTHER).json() == []


def test_unconfigured_connection_fails_closed(client, auth_headers, monkeypatch):
    monkeypatch.setattr(github, "settings", replace(github.settings, github_client_id=""))
    assert client.post("/api/v1/connections/github/start", headers=auth_headers).status_code == 503


def test_private_provider_access_requires_connection_and_permission(monkeypatch):
    real_client = httpx.Client
    content = base64.b64encode(b"# My private Python project").decode()
    def handler(request):
        assert request.url.host == "api.github.com"
        assert request.headers.get("authorization") == "Bearer " + TOKEN
        path = request.url.path
        if path == "/repos/me/private":
            return httpx.Response(200, json={"private": True, "default_branch": "main"})
        if "/commits/" in path:
            return httpx.Response(200, json={"sha": "a" * 40})
        if "/git/trees/" in path:
            return httpx.Response(200, json={"tree": [{"path": "README.md", "type": "blob", "size": 28}]})
        return httpx.Response(200, json={"type": "file", "encoding": "base64", "content": content})
    monkeypatch.setattr(github_import.httpx, "Client", lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    preview = github_import.connected_preview("https://github.com/me/private", TOKEN)
    assert preview["is_private"] is True and len(preview["files"]) == 1
    with pytest.raises(github_import.ImportFailure, match="Only public"):
        github_import._preview("https://github.com/me/private", TOKEN, allow_private=False)
    monkeypatch.setattr(github_import.httpx, "Client", lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(404))))
    with pytest.raises(github_import.ImportFailure):
        github_import.connected_preview("https://github.com/me/not-installed", TOKEN)
