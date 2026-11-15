import time, uuid
from collections import defaultdict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .config import get_settings

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.request_id = request.headers.get("x-request-id", uuid.uuid4().hex)[:64]
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
                continue
            response.headers.setdefault(k, v)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window limiter. Uses Redis when REDIS_URL is set (shared across replicas), memory otherwise."""

    def __init__(self, app):
        super().__init__(app)
        s = get_settings()
        self.redis = None
        if s.redis_url:
            import redis
            self.redis = redis.Redis.from_url(s.redis_url)
        self.mem: dict[str, deque] = defaultdict(deque)

    def _hit(self, key: str, limit: int) -> bool:
        window = int(time.time() // 60)
        if self.redis is not None:
            try:
                k = f"rl:{key}:{window}"
                n = self.redis.incr(k)
                if n == 1:
                    self.redis.expire(k, 70)
                return n <= limit
            except Exception:
                pass  # degrade to in-memory limiting if Redis is unavailable
        q = self.mem[key]; now = time.time()
        while q and q[0] < now - 60:
            q.popleft()
        q.append(now)
        return len(q) <= limit

    async def dispatch(self, request, call_next):
        s = get_settings()
        ip = request.client.host if request.client else "unknown"
        is_auth = request.url.path.startswith("/auth/") and request.method == "POST"
        limit = s.auth_rate_limit_per_minute if is_auth else s.rate_limit_per_minute
        if not self._hit(f"{'auth' if is_auth else 'api'}:{ip}", limit):
            return JSONResponse({"detail": "Too many requests"}, status_code=429, headers={"Retry-After": "60"})
        return await call_next(request)
