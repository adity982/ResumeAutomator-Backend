from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections import Counter, defaultdict, deque
from threading import Lock

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger("resume_automator.api")


class ApiMetrics:
    def __init__(self):
        self.started_at = time.time()
        self.total_requests = 0
        self.total_duration_ms = 0.0
        self.status_counts: Counter[str] = Counter()
        self.path_counts: Counter[str] = Counter()
        self.lock = Lock()
        self.recent_durations: deque[float] = deque(maxlen=1000)

    def record(self, path: str, status: int, duration_ms: float) -> None:
        with self.lock:
            self.total_requests += 1
            self.total_duration_ms += duration_ms
            self.recent_durations.append(duration_ms)
            self.status_counts[str(status)] += 1
            normalized = re.sub(r"/\d+(?=/|$)", "/{id}", path)[:120]
            self.path_counts[normalized if len(self.path_counts) < 100 or normalized in self.path_counts else "other"] += 1

    def snapshot(self) -> dict:
        with self.lock:
            durations = sorted(self.recent_durations)
            return {
                "uptime_seconds": round(time.time() - self.started_at, 1),
                "requests_total": self.total_requests,
                "average_duration_ms": round(self.total_duration_ms / self.total_requests, 2) if self.total_requests else 0,
                "status_counts": dict(self.status_counts),
                "path_counts": dict(self.path_counts),
                "recent_p95_ms": durations[min(len(durations) - 1, int(len(durations) * .95))] if durations else None,
                "recent_latency_samples": len(durations),
            }


api_metrics = ApiMetrics()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:128]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        api_metrics.record(request.url.path, response.status_code, duration_ms)
        logger.info(
            json.dumps(
                {
                    "event": "request_complete",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit_per_minute: int = 120):
        super().__init__(app)
        self.limit = max(limit_per_minute, 1)
        self.entries: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health/live", "/health/ready"}:
            return await call_next(request)
        identity = request.client.host if request.client else "unknown"
        key = identity
        now = time.monotonic()
        with self.lock:
            if len(self.entries) > 10_000:
                self.entries = defaultdict(deque, {k: v for k, v in self.entries.items() if v and v[-1] >= now - 60})
                if len(self.entries) > 10_000 and key not in self.entries:
                    return JSONResponse(status_code=429, content={"error": {"code": "busy", "message": "Service is busy. Retry shortly."}})
            bucket = self.entries[key]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "rate_limited", "message": "Too many requests. Try again shortly."}},
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)
        return await call_next(request)


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = self.max_bytes + 1
        if declared > self.max_bytes or declared < 0:
            return await JSONResponse(status_code=413, content={"error": {"code": "body_too_large", "message": "Request body exceeds the upload limit."}})(scope, receive, send)
        total = 0
        exceeded = False
        replacement_sent = False
        async def bounded_receive():
            nonlocal total, exceeded
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    exceeded = True
                    raise HTTPException(413, "Request body exceeds the upload limit.")
            return message
        async def bounded_send(message):
            nonlocal replacement_sent
            if exceeded:
                # Multipart/JSON parsers may translate receive errors to 400.
                # Preserve a stable 413 contract without buffering the body.
                if message["type"] == "http.response.start" and not replacement_sent:
                    replacement_sent = True
                    await JSONResponse(status_code=413, content={"error": {"code": "body_too_large", "message": "Request body exceeds the upload limit."}})(scope, receive, send)
                return
            await send(message)
        return await self.app(scope, bounded_receive, bounded_send)
