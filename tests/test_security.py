import pytest

from app.services.scraper import UnsafeURL, normalize_url, validate_public_url


def test_url_normalization_rejects_credentials_and_unsafe_schemes():
    with pytest.raises(UnsafeURL):
        normalize_url("file:///etc/passwd")
    with pytest.raises(UnsafeURL):
        normalize_url("https://user:password@example.com/job")


@pytest.mark.parametrize("url", ["http://localhost/job", "http://metadata.google.internal/latest", "http://127.0.0.1/job", "http://[::1]/job"])
@pytest.mark.asyncio
async def test_private_and_metadata_destinations_are_blocked(url):
    with pytest.raises(UnsafeURL):
        await validate_public_url(url)


@pytest.mark.asyncio
async def test_fetch_pins_the_validated_ip_but_preserves_tls_hostname(monkeypatch):
    from app.services import scraper
    async def resolve(url):
        return 'https://jobs.example.com/role', {'93.184.216.34'}
    monkeypatch.setattr(scraper, 'resolve_public_url', resolve)
    target, host_header, tls_hostname = await scraper.pinned_request('https://jobs.example.com/role')
    assert target.host == '93.184.216.34'
    assert host_header == tls_hostname == 'jobs.example.com'


def test_body_limits_cover_declared_and_chunked_requests(client, auth_headers):
    from app.config import settings
    large = b'x' * (settings.max_upload_bytes + 70_000)
    headers = dict(auth_headers, Origin='http://localhost:5173', **{'Content-Type': 'application/json'})
    declared = client.post('/api/v1/analysis', headers=headers, content=large)
    assert declared.status_code == 413
    assert declared.headers['access-control-allow-origin'] == 'http://localhost:5173'
    chunked = client.post('/api/v1/analysis', headers=headers, content=iter([large[:3_000_000], large[3_000_000:]]))
    assert chunked.status_code == 413


def test_firebase_identity_requires_an_explicit_verified_email(monkeypatch):
    from app import auth
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    from types import SimpleNamespace
    monkeypatch.setattr(auth, 'settings', SimpleNamespace(auth_mode='firebase', firebase_project_id='test'))
    monkeypatch.setattr(auth.id_token, 'verify_firebase_token', lambda *args, **kwargs: {'sub': 'user', 'email': 'person@example.com'})
    with pytest.raises(HTTPException):
        auth.verify_user(HTTPAuthorizationCredentials(scheme='Bearer', credentials='test'))
