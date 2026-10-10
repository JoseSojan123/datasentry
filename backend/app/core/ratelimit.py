"""In-process sliding-window rate limiter.

Adequate for a single API instance (the portfolio deployment). With several replicas each instance
enforces its own window; a shared store such as Redis would be needed for a global limit.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import get_settings


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, window - (now - q[0])
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory under key churn
                for k in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[k]
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    """Client address for rate limiting and audit.

    X-Forwarded-For is client-controlled except for the entries appended by our own proxies, so it is
    only used when TRUSTED_PROXY_HOPS > 0, taking the entry that many hops from the right.
    """
    hops = get_settings().trusted_proxy_hops
    fwd = request.headers.get("x-forwarded-for")
    if hops > 0 and fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-min(hops, len(parts))]
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str):
    """FastAPI dependency enforcing a per-client limit for a named bucket."""

    def dep(request: Request) -> None:
        s = get_settings()
        limit = {
            "upload": s.rate_limit_upload_per_min,
            "predictions": s.rate_limit_predictions_per_min,
            "auth": s.rate_limit_auth_per_min,
        }.get(bucket, s.rate_limit_default_per_min)
        # Sign-in endpoints are keyed by address only: the credential headers there are attacker-chosen.
        auth = "" if bucket == "auth" else (
            request.headers.get("authorization", "")[-16:] or request.headers.get("x-api-key", "")[:12])
        ok, retry = limiter.hit(f"{bucket}:{client_ip(request)}:{auth}", limit)
        if not ok:
            raise HTTPException(429, f"Rate limit exceeded for {bucket} requests; retry in {int(retry) + 1}s.",
                                headers={"Retry-After": str(int(retry) + 1)})

    return dep
