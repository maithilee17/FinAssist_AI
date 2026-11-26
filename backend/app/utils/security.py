"""Argon2 password hashing, JWT handling, cookies, and CSRF helpers."""

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, Request, Response, status
from pwdlib import PasswordHash

from app.config import get_settings

settings = get_settings()
password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("FinAssist-Dummy-Password-Only-For-Timing")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> tuple[bool, str | None]:
    """Verify a password and return an upgraded hash when parameters have changed."""

    try:
        return password_hash.verify_and_update(password, hashed_password)
    except Exception:  # noqa: BLE001 - malformed stored hashes must fail closed.
        return False, None


def create_access_token(
    user_id: UUID,
    *,
    expires_delta: timedelta | None = None,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": issued_at,
        "exp": expires_at,
        "jti": str(uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "type", "iat", "exp", "jti", "iss", "aud"]},
    )


def set_auth_cookies(response: Response, access_token: str) -> None:
    csrf_token = secrets.token_urlsafe(32)
    cookie_options = {
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
        "max_age": settings.access_token_expire_seconds,
    }
    response.set_cookie(
        settings.auth_cookie_name, access_token, httponly=True, **cookie_options
    )
    response.set_cookie(
        settings.csrf_cookie_name, csrf_token, httponly=False, **cookie_options
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def require_csrf(request: Request) -> None:
    """Require double-submit CSRF validation for cookie-authenticated mutations."""

    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return

    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed"
        )
