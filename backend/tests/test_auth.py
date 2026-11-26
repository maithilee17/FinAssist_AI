"""Authentication API behavior and security tests."""

from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from app.utils.security import create_access_token

pytestmark = pytest.mark.anyio

REGISTER_PAYLOAD = {
    "full_name": "Mihir Sharma",
    "email": "mihir@example.com",
    "password": "SecureFinance123!",
}


async def register(client: httpx.AsyncClient, **overrides: str) -> httpx.Response:
    return await client.post(
        "/api/auth/register", json={**REGISTER_PAYLOAD, **overrides}
    )


async def login(client: httpx.AsyncClient, **overrides: str) -> httpx.Response:
    payload = {
        "email": REGISTER_PAYLOAD["email"],
        "password": REGISTER_PAYLOAD["password"],
    }
    return await client.post("/api/auth/login", json={**payload, **overrides})


async def test_successful_registration_hashes_password(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == REGISTER_PAYLOAD["email"]
    assert "password" not in body
    assert "hashed_password" not in body

    async with session_factory() as session:
        user = await session.scalar(
            select(User).where(User.email == REGISTER_PAYLOAD["email"])
        )
    assert user is not None
    assert user.hashed_password.startswith("$argon2id$")
    assert user.hashed_password != REGISTER_PAYLOAD["password"]


async def test_duplicate_email_is_rejected_case_insensitively(
    client: httpx.AsyncClient,
) -> None:
    assert (await register(client)).status_code == 201
    response = await register(client, email="MIHIR@EXAMPLE.COM")
    assert response.status_code == 409
    assert response.json()["detail"] == "An account already exists"


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({**REGISTER_PAYLOAD, "email": "not-an-email"}, 422),
        ({**REGISTER_PAYLOAD, "password": "weakpassword"}, 422),
        (
            {
                "email": REGISTER_PAYLOAD["email"],
                "password": REGISTER_PAYLOAD["password"],
            },
            422,
        ),
    ],
)
async def test_registration_validation(
    client: httpx.AsyncClient, payload: dict[str, str], expected_status: int
) -> None:
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == expected_status


async def test_successful_login_returns_token_sets_cookie_and_allows_me(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    response = await login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == REGISTER_PAYLOAD["email"]
    assert "finassist_access_token" in response.cookies
    assert "finassist_csrf_token" in response.cookies
    auth_cookie_header = next(
        header
        for header in response.headers.get_list("set-cookie")
        if "finassist_access_token" in header
    )
    assert "HttpOnly" in auth_cookie_header
    assert "SameSite=lax" in auth_cookie_header

    me_response = await client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["full_name"] == REGISTER_PAYLOAD["full_name"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        (REGISTER_PAYLOAD["email"], "IncorrectPassword123!"),
        ("unknown@example.com", REGISTER_PAYLOAD["password"]),
    ],
)
async def test_login_uses_same_error_for_unknown_email_and_bad_password(
    client: httpx.AsyncClient, email: str, password: str
) -> None:
    await register(client)
    response = await login(client, email=email, password=password)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_valid_bearer_token_authenticates(client: httpx.AsyncClient) -> None:
    registration = await register(client)
    token = create_access_token(UUID(registration.json()["id"]))
    response = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


async def test_missing_invalid_and_expired_tokens_are_rejected(
    client: httpx.AsyncClient,
) -> None:
    missing = await client.get("/api/auth/me")
    invalid = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-valid-token"}
    )

    registration = await register(client)
    expired_token = create_access_token(
        UUID(registration.json()["id"]), expires_delta=timedelta(seconds=-1)
    )
    expired = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert expired.status_code == 401


async def test_inactive_account_is_forbidden(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registration = await register(client)
    user_id = UUID(registration.json()["id"])
    token = create_access_token(user_id)
    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.is_active = False
        await session.commit()

    response = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


async def test_logout_requires_csrf_and_clears_session(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    await login(client)

    rejected = await client.post("/api/auth/logout")
    assert rejected.status_code == 403

    csrf = client.cookies.get("finassist_csrf_token")
    response = await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401
