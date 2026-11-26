"""Reusable authentication and authorization dependencies."""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.utils.security import decode_access_token

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    access_cookie: Annotated[
        str | None, Cookie(alias=settings.auth_cookie_name)
    ] = None,
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials if credentials else access_cookie
    if not token:
        raise unauthorized

    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise unauthorized
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise unauthorized from exc

    user = await db.get(User, user_id)
    if user is None:
        raise unauthorized
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
