import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .config import get_settings
from .db import Base, engine, SessionLocal
from .middleware import SecurityHeadersMiddleware, RateLimitMiddleware
from .routers import auth, patients, clinical, documents, ai, admin

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("caresync")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.is_production:
        Base.metadata.create_all(bind=engine)  # production schema is managed by Alembic migrations
    if settings.seed_demo:
        from .seed import seed
        seed()
    yield


app = FastAPI(title="CareSync AI API", version="2.0.0", lifespan=lifespan,
              description="Care coordination API. Not a medical device; not for autonomous clinical decisions.",
              docs_url=None if settings.is_production else "/docs",
              redoc_url=None, openapi_url=None if settings.is_production else "/openapi.json")
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never leak stack traces or PHI in error responses.
    log.error("unhandled error %s on %s rid=%s", type(exc).__name__, request.url.path, getattr(request.state, "request_id", ""))
    return JSONResponse({"detail": "Internal error", "request_id": getattr(request.state, "request_id", "")}, status_code=500)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready", "region": settings.data_region}


@app.get("/", tags=["ops"])
def root():
    """Friendly landing so opening http://localhost:8000 does not show a bare 404."""
    return {
        "service": "CareSync AI API",
        "version": "2.0.0",
        "status": "ok",
        "docs": "/docs" if not settings.is_production else None,
        "health": "/health",
        "ready": "/ready",
        "hint": "Open the web UI at http://localhost:3000 (local) or https://localhost (Docker + Caddy).",
    }


for r in (auth.router, patients.router, clinical.router, documents.router, ai.router, admin.router):
    app.include_router(r)
