from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections import Counter, defaultdict, deque
from threading import Lock

from fastapi import Request
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

    def record(self, path: str, status: int, duration_ms: float) -> None:
        with self.lock:
            self.total_requests += 1
            self.total_duration_ms += duration_ms
            self.status_counts[str(status)] += 1
            self.path_counts[path] += 1

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "uptime_seconds": round(time.time() - self.started_at, 1),
                "requests_total": self.total_requests,
                "average_duration_ms": round(self.total_duration_ms / self.total_requests, 2) if self.total_requests else 0,
                "status_counts": dict(self.status_counts),
                "path_counts": dict(self.path_counts),
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
        auth = request.headers.get("authorization", "")
        identity = hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else (request.client.host if request.client else "unknown")
        key = f"{identity}:{request.url.path}"
        now = time.monotonic()
        with self.lock:
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
