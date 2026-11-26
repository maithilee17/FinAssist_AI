"""Deployment-sensitive configuration validation."""

import pytest
from pydantic import ValidationError
from sqlalchemy import make_url

from app.config import Settings

PRODUCTION_SECRET = "production-test-secret-that-is-longer-than-32-characters"


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key=PRODUCTION_SECRET,
            cookie_secure=False,
            cors_origins="https://finassist.example.com",
        )


@pytest.mark.parametrize(
    "origins",
    ["*", "http://finassist.example.com", ""],
)
def test_production_requires_explicit_https_cors_origins(origins: str) -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key=PRODUCTION_SECRET,
            cookie_secure=True,
            cors_origins=origins,
        )


def test_production_accepts_explicit_https_origin_and_secure_cookie() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key=PRODUCTION_SECRET,
        cookie_secure=True,
        cors_origins="https://finassist.example.com",
    )

    assert settings.cors_origin_list == ["https://finassist.example.com"]


def test_postgres_components_safely_encode_reserved_password_characters() -> None:
    password = "local:p@ss/word?#value"
    settings = Settings(
        _env_file=None,
        postgres_host="postgres",
        postgres_port=5432,
        postgres_db="finassist",
        postgres_user="finassist",
        postgres_password=password,
    )

    parsed = make_url(settings.database_url)
    assert parsed.host == "postgres"
    assert parsed.port == 5432
    assert parsed.database == "finassist"
    assert parsed.username == "finassist"
    assert parsed.password == password
    assert "%%40" in settings.alembic_database_url
    assert settings.alembic_database_url.replace("%%", "%") == settings.database_url
