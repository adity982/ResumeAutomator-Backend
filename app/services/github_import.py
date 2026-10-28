"""Public GitHub ingestion, pinned to a commit and bounded before decoding."""
from __future__ import annotations

import base64
import hashlib
import re
import time
from urllib.parse import quote, urlsplit

import httpx

from ..config import settings

MAX_FILES = 16
MAX_FILE_BYTES = 48_000
MAX_TOTAL_BYTES = 500_000
EXCLUDED = {"node_modules", "vendor", "dist", "build", ".git", ".venv", "venv", "__pycache__", "coverage", ".next", "fixtures", "migrations"}
MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "go.mod", "cargo.toml", "pom.xml", "dockerfile"}
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".sql", ".md"}


class ImportFailure(ValueError):
    pass


def repository_name(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment:
        raise ImportFailure("Use an HTTPS public github.com repository URL without a query or fragment.")
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", p) and p not in {".", ".."} for p in parts):
        raise ImportFailure("Use a repository URL such as https://github.com/owner/project.")
    return "/".join(parts)


def allowed(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    if len(path) > 400 or any(p in EXCLUDED or p.startswith(".") for p in parts):
        return False
    if any(term in name for term in ("lock", "secret", "credential", ".min.", ".map", ".env", "snapshot")):
        return False
    return name in MANIFESTS or any(name.endswith(ext) for ext in EXTENSIONS)


def priority(path: str):
    name = path.lower().split("/")[-1]
    return (0 if name.startswith("readme") else 1 if name in MANIFESTS else 2 if "test" in path.lower() else 3, len(path), path)


def public_preview(url: str) -> dict:
    return _preview(url, settings.github_token, allow_private=False)


def connected_preview(url: str, token: str) -> dict:
    return _preview(url, token, allow_private=True)


def _preview(url: str, token: str, *, allow_private: bool) -> dict:
    repository = repository_name(url)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ResumeAutomator"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # API URLs are constructed exclusively from validated repository names and paths.
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=15, follow_redirects=False, trust_env=False) as client:
        deadline = time.monotonic() + 70
        def get(path: str, limit: int = 2_000_000):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImportFailure("Import preview timed out. Retry with a smaller repository.")
            with client.stream("GET", path, timeout=min(15, remaining)) as response:
                if response.status_code in {403, 429}:
                    raise ImportFailure("GitHub rate limit or repository permission denied. Check access or retry later.")
                if response.status_code != 200:
                    raise ImportFailure("GitHub could not read this public repository or file.")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise ImportFailure("Import preview exceeded its time limit.")
                    size += len(chunk)
                    if size > limit:
                        raise ImportFailure("GitHub response exceeds the import limit.")
                    chunks.append(chunk)
                import json
                return json.loads(b"".join(chunks))

        metadata = get(f"/repos/{repository}")
        if metadata.get("private") and not allow_private:
            raise ImportFailure("Only public repositories are supported. Private repository access is not enabled.")
        commit = get(f"/repos/{repository}/commits/{quote(metadata['default_branch'], safe='')}")["sha"]
        tree = get(f"/repos/{repository}/git/trees/{commit}?recursive=1")
        if tree.get("truncated"):
            raise ImportFailure("Repository tree is too large. Import a smaller focused repository.")
        paths = sorted((item["path"] for item in tree.get("tree", []) if item.get("type") == "blob" and item.get("mode") != "120000" and item.get("size", MAX_FILE_BYTES + 1) <= MAX_FILE_BYTES and allowed(item["path"])), key=priority)[:MAX_FILES]
        files, total = [], 0
        for path in paths:
            file = get(f"/repos/{repository}/contents/{quote(path, safe='/')}?ref={commit}", 100_000)
            if file.get("type") != "file" or file.get("encoding") != "base64":
                continue
            try:
                raw = base64.b64decode(file["content"], validate=False)
                if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
                    continue
                text = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
            if re.search(r"(?:-----BEGIN .*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})", text):
                continue
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                break
            files.append({"path": path, "content": text, "bytes": len(raw), "hash": hashlib.sha256(raw).hexdigest()})
        if not files:
            raise ImportFailure("No supported, bounded text files were found.")
        return {"repository": repository, "commit_sha": commit, "source_url": f"https://github.com/{repository}", "description": (metadata.get("description") or "")[:1000], "is_fork": bool(metadata.get("fork")), "is_private": bool(metadata.get("private")), "files": files}


def chunk_file(path: str, content: str) -> list[dict]:
    lines = content.splitlines()
    chunks, start = [], 0
    # Keep documentation headings and top-level code symbols together where possible.
    for index in range(1, len(lines) + 1):
        boundary = index == len(lines) or index - start >= 35 or (index - start >= 8 and re.match(r"^(?:#{1,3} |(?:async )?def |class |export (?:function|class) )", lines[index] if index < len(lines) else ""))
        if boundary:
            text = "\n".join(lines[start:index])[:6000]
            if text.strip():
                chunks.append({"path": path, "start_line": start + 1, "end_line": index, "content": text, "content_hash": hashlib.sha256(text.encode()).hexdigest(), "kind": "documentation" if path.lower().endswith(".md") else "manifest" if path.lower().split("/")[-1] in MANIFESTS else "implementation"})
            start = index
        if len(chunks) >= 20:
            break
    return chunks
