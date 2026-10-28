from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development").lower()
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./resume_app.db")
    auth_mode: str = os.getenv("AUTH_MODE", "firebase").lower()
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "20"))
    scrape_cache_size: int = int(os.getenv("SCRAPE_CACHE_SIZE", "128"))
    scrape_cache_ttl_seconds: int = int(os.getenv("SCRAPE_CACHE_TTL_SECONDS", "600"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    docs_enabled: bool = _as_bool(os.getenv("DOCS_ENABLED"), True)
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "lexical").lower()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    model_cache_dir: str = os.getenv("MODEL_CACHE_DIR", ".cache/models")
    github_token: str = os.getenv("GITHUB_PUBLIC_TOKEN", "")
    github_client_id: str = os.getenv("GITHUB_APP_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_APP_CLIENT_SECRET", "")
    github_redirect_uri: str = os.getenv("GITHUB_REDIRECT_URI", "")
    github_app_slug: str = os.getenv("GITHUB_APP_SLUG", "")
    connection_encryption_key: str = os.getenv("CONNECTION_ENCRYPTION_KEY", "")
    worker_lease_seconds: int = int(os.getenv("WORKER_LEASE_SECONDS", "300"))

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def validate(self) -> None:
        if self.auth_mode not in {"firebase", "development"}:
            raise RuntimeError("AUTH_MODE must be 'firebase' or 'development'.")
        if self.app_env == "production" and self.auth_mode == "development":
            raise RuntimeError("Development authentication is forbidden in production.")
        if self.auth_mode == "firebase" and not self.firebase_project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is required when AUTH_MODE=firebase.")
        if self.embedding_provider not in {"lexical", "fastembed"}:
            raise RuntimeError("EMBEDDING_PROVIDER must be lexical or fastembed.")


settings = Settings()
