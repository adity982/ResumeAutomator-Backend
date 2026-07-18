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
