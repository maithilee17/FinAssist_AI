"""Environment-driven application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Validated settings loaded from environment variables or a root .env file."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "FinAssist AI"
    app_version: str = "0.6.0"
    app_env: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api"

    database_url: str = (
        "postgresql+asyncpg://finassist:finassist_local_only@localhost:5432/finassist"
    )
    postgres_host: str | None = None
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "finassist"
    postgres_user: str = "finassist"
    postgres_password: SecretStr | None = None
    database_connect_timeout_seconds: float = 3.0

    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_ssl: bool = False
    chroma_timeout_seconds: float = 3.0

    cors_origins: str = "http://localhost:5173"
    upload_dir: Path = Path("uploads")
    max_upload_size_mb: int = Field(default=50, ge=1, le=500)
    upload_read_chunk_bytes: int = Field(
        default=1024 * 1024, ge=64 * 1024, le=8 * 1024 * 1024
    )
    chunk_size_tokens: int = Field(default=500, ge=50, le=5000)
    chunk_overlap_tokens: int = Field(default=100, ge=0, le=1000)

    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_dpi: int = Field(default=200, ge=72, le=600)
    ocr_max_page_pixels: int = Field(default=25_000_000, ge=1_000_000, le=100_000_000)
    ocr_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    tessdata_dir: Path | None = None

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str | None = "cpu"
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    embedding_expected_dimension: int = Field(default=384, ge=1, le=8192)
    embedding_model_revision: str | None = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_local_files_only: bool = False
    embedding_query_prefix: str = (
        "Represent this sentence for searching relevant passages: "
    )
    chroma_collection: str = "financial_document_chunks"
    rag_top_k: int = Field(default=5, ge=1, le=25)
    rag_min_similarity: float = Field(default=0.25, ge=-1.0, le=1.0)
    rag_source_excerpt_chars: int = Field(default=600, ge=100, le=2000)
    bm25_k1: float = Field(default=1.5, gt=0.0, le=5.0)
    bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)
    bm25_epsilon: float = Field(default=0.25, ge=0.0, le=2.0)
    bm25_cache_users: int = Field(default=128, ge=1, le=10000)
    rrf_constant: int = Field(default=60, ge=1, le=1000)
    adaptive_exact_term_threshold: int = Field(default=1, ge=1, le=10)
    evidence_relevance_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    evidence_sufficiency_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    evidence_weak_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    evidence_max_top_k: int = Field(default=15, ge=1, le=50)
    evidence_max_retrieval_attempts: int = Field(default=2, ge=0, le=5)
    answer_max_revision_attempts: int = Field(default=1, ge=0, le=3)
    claim_support_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    llm_provider: Literal["ollama"] = "ollama"
    llm_timeout_seconds: float = Field(default=120.0, ge=1.0, le=300.0)
    llm_max_output_tokens: int = Field(default=800, ge=64, le=4096)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = Field(default="qwen2.5:7b", min_length=1, pattern=r"^\S+$")
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=32768)
    ollama_connect_timeout_seconds: float = Field(default=5.0, ge=1.0, le=60.0)

    jwt_secret_key: str = "replace-with-a-long-random-secret"
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "finassist-ai"
    jwt_audience: str = "finassist-ai-web"
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    auth_cookie_name: str = "finassist_access_token"
    csrf_cookie_name: str = "finassist_csrf_token"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.postgres_host and self.postgres_password is not None:
            self.database_url = URL.create(
                drivername="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        if self.app_env.lower() in {"production", "staging"}:
            if len(self.jwt_secret_key) < 32 or self.jwt_secret_key.startswith(
                "replace-"
            ):
                raise ValueError(
                    "JWT_SECRET_KEY must be a strong environment secret outside development"
                )
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true outside development")
            origins = self.cors_origin_list
            if not origins or "*" in origins:
                raise ValueError(
                    "CORS_ORIGINS must list explicit HTTPS origins outside development"
                )
            if any(not origin.startswith("https://") for origin in origins):
                raise ValueError("CORS_ORIGINS must use HTTPS outside development")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true when COOKIE_SAMESITE is none")
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError(
                "CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_SIZE_TOKENS"
            )
        if self.evidence_weak_threshold > self.evidence_relevance_threshold:
            raise ValueError(
                "EVIDENCE_WEAK_THRESHOLD must not exceed EVIDENCE_RELEVANCE_THRESHOLD"
            )
        if self.evidence_relevance_threshold > self.evidence_sufficiency_threshold:
            raise ValueError(
                "EVIDENCE_RELEVANCE_THRESHOLD must not exceed EVIDENCE_SUFFICIENCY_THRESHOLD"
            )
        if self.evidence_max_top_k < self.rag_top_k:
            raise ValueError("EVIDENCE_MAX_TOP_K must be at least RAG_TOP_K")
        from urllib.parse import urlsplit

        endpoint = urlsplit(self.ollama_base_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError(
                "OLLAMA_BASE_URL must be an HTTP service URL without credentials, query or fragment"
            )
        if endpoint.hostname == "ollama.com" or endpoint.hostname.endswith(
            ".ollama.com"
        ):
            raise ValueError("OLLAMA_BASE_URL must point to a local Ollama service")
        if "cloud" in self.ollama_model.lower():
            raise ValueError(
                "OLLAMA_MODEL must be a locally installed model, not a cloud model"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def alembic_database_url(self) -> str:
        """Escape percent signs consumed by Alembic's INI interpolation layer."""

        return self.database_url.replace("%", "%%")

    @property
    def chroma_base_url(self) -> str:
        scheme = "https" if self.chroma_ssl else "http"
        return f"{scheme}://{self.chroma_host}:{self.chroma_port}"

    @property
    def access_token_expire_seconds(self) -> int:
        return self.access_token_expire_minutes * 60

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""

    return Settings()
