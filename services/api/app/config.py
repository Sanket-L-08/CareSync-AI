"""Central configuration. Fails closed in production when secrets are unsafe."""
import os
from functools import lru_cache


def _bool(v: str | None, default: bool = False) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        e = os.environ
        self.app_env = e.get("APP_ENV", "development")
        self.secret_key = e.get("SECRET_KEY", "")
        self.data_encryption_key = e.get("DATA_ENCRYPTION_KEY", "")  # base64 32 bytes
        self.database_url = e.get("DATABASE_URL", "sqlite:///./caresync.db")
        self.redis_url = e.get("REDIS_URL", "")
        self.cors_origins = [o.strip() for o in e.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
        self.allowed_hosts = [h.strip() for h in e.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]
        self.access_ttl_min = int(e.get("ACCESS_TOKEN_MINUTES", "15"))
        self.refresh_ttl_days = int(e.get("REFRESH_TOKEN_DAYS", "7"))
        self.max_failed_logins = int(e.get("MAX_FAILED_LOGINS", "5"))
        self.lockout_minutes = int(e.get("LOCKOUT_MINUTES", "15"))
        self.require_mfa_for_staff = _bool(e.get("REQUIRE_MFA_FOR_STAFF"), True)
        self.allow_clinician_self_signup = _bool(e.get("ALLOW_CLINICIAN_SELF_SIGNUP"), False)
        self.seed_demo = _bool(e.get("SEED_DEMO"), False)
        self.max_upload_mb = int(e.get("MAX_UPLOAD_MB", "12"))
        self.storage_backend = e.get("STORAGE_BACKEND", "local")  # local | s3
        self.local_storage_dir = e.get("LOCAL_STORAGE_DIR", "./private-storage")
        self.s3_bucket = e.get("S3_BUCKET", "")
        self.s3_endpoint = e.get("S3_ENDPOINT_URL") or None
        self.s3_region = e.get("S3_REGION", "us-east-1")
        self.s3_kms_key_id = e.get("S3_KMS_KEY_ID") or None
        self.default_timezone = e.get("DEFAULT_TIMEZONE", "UTC")
        self.data_region = e.get("DATA_REGION", "unspecified")
        self.ai_base_url = e.get("AI_BASE_URL", "").rstrip("/")
        self.ai_api_key = e.get("AI_API_KEY", "")
        self.ai_model = e.get("AI_MODEL", "")
        self.alert_webhook_url = e.get("ALERT_WEBHOOK_URL", "")
        self.rate_limit_per_minute = int(e.get("RATE_LIMIT_PER_MINUTE", "120"))
        self.auth_rate_limit_per_minute = int(e.get("AUTH_RATE_LIMIT_PER_MINUTE", "10"))

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate(self) -> None:
        if not self.is_production:
            if not self.secret_key:
                self.secret_key = "dev-only-insecure-secret-key-not-for-production-use"
            return
        problems = []
        if len(self.secret_key) < 48:
            problems.append("SECRET_KEY must be at least 48 random characters")
        if not self.data_encryption_key:
            problems.append("DATA_ENCRYPTION_KEY is required")
        if self.database_url.startswith("sqlite"):
            problems.append("PostgreSQL DATABASE_URL is required in production")
        if not self.redis_url:
            problems.append("REDIS_URL is required in production")
        if self.storage_backend != "s3" or not self.s3_bucket:
            problems.append("STORAGE_BACKEND=s3 with S3_BUCKET is required in production")
        if self.seed_demo:
            problems.append("SEED_DEMO must be false in production")
        if "*" in self.cors_origins or any(o.startswith("http://") for o in self.cors_origins):
            problems.append("CORS_ORIGINS must list explicit https origins in production")
        if "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must list explicit hostnames in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
