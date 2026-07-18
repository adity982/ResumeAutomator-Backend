from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from ..config import settings


class UnsafeURL(ValueError):
    pass


@dataclass
class CacheEntry:
    expires_at: float
    value: dict


class TTLCache:
    def __init__(self, max_size: int, ttl_seconds: int):
        self.max_size = max(max_size, 1)
        self.ttl_seconds = max(ttl_seconds, 1)
        self.values: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = Lock()

    def get(self, key: str) -> dict | None:
        now = time.monotonic()
        with self.lock:
            entry = self.values.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self.values[key]
                return None
            self.values.move_to_end(key)
            return dict(entry.value)

    def set(self, key: str, value: dict) -> None:
        with self.lock:
            self.values[key] = CacheEntry(time.monotonic() + self.ttl_seconds, dict(value))
            self.values.move_to_end(key)
            while len(self.values) > self.max_size:
                self.values.popitem(last=False)


cache = TTLCache(settings.scrape_cache_size, settings.scrape_cache_ttl_seconds)


def normalize_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURL("Only HTTP and HTTPS URLs are allowed.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeURL("URL must contain a public hostname and no embedded credentials.")
    hostname = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    if (parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443):
        port = None
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{rendered_host}:{port}" if port else rendered_host
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


async def validate_public_url(raw_url: str) -> str:
    normalized = normalize_url(raw_url)
    hostname = urlsplit(normalized).hostname
    if hostname in {"localhost", "metadata.google.internal"} or hostname.endswith(".localhost"):
        raise UnsafeURL("Local and metadata destinations are blocked.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL("Hostname could not be resolved.") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses or any(_blocked_ip(address) for address in addresses):
        raise UnsafeURL("The destination resolves to a blocked network.")
    return normalized


async def scrape_job(raw_url: str) -> tuple[dict, bool]:
    current_url = await validate_public_url(raw_url)
    cached = cache.get(current_url)
    if cached is not None:
        return cached, True

    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    timeout = httpx.Timeout(12.0, connect=5.0)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ResumeAutomator/1.0; +https://github.com/adity982)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
    }
    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=False, headers=headers) as client:
        for _ in range(4):
            response = await client.get(current_url)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURL("Redirect response did not include a destination.")
                current_url = await validate_public_url(urljoin(current_url, location))
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
                raise UnsafeURL("Destination did not return readable HTML or text.")
            body = response.content
            if len(body) > 2_000_000:
                raise UnsafeURL("Destination response exceeded the 2 MB limit.")
            break
        else:
            raise UnsafeURL("Too many redirects.")

    soup = BeautifulSoup(body, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        element.decompose()
    text = " ".join(soup.get_text(separator=" ", strip=True).split())
    if len(text) < 50:
        raise UnsafeURL("The page did not contain enough readable job text.")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "Job description")[:240]
    result = {"title": title, "description": text[:50_000], "source_url": current_url}
    cache.set(normalize_url(raw_url), result)
    return result, False
