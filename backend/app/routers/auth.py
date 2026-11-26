"""Registration, login, logout, and current-account endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_db
from app.dependencies import CurrentUser
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    UserResponse,
)
from app.utils.security import (
    DUMMY_PASSWORD_HASH,
    clear_auth_cookies,
    create_access_token,
    hash_password,
    require_csrf,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(payload: RegisterRequest, db: DbSession) -> User:
    existing = await db.scalar(select(User.id).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account already exists"
        )

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=await run_in_threadpool(
            hash_password, payload.password.get_secret_value()
        ),
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account already exists"
        ) from exc
    return user


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest, response: Response, db: DbSession
) -> AuthResponse:
    user = await db.scalar(select(User).where(User.email == payload.email))
    supplied_password = payload.password.get_secret_value()

    if user is None:
        await run_in_threadpool(verify_password, supplied_password, DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    valid, updated_hash = await run_in_threadpool(
        verify_password, supplied_password, user.hashed_password
    )
    if not valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if updated_hash:
        user.hashed_password = updated_hash
        await db.commit()

    access_token = create_access_token(user.id)
    set_auth_cookies(response, access_token)
    return AuthResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_seconds,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> User:
    return current_user


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request, response: Response, current_user: CurrentUser
) -> MessageResponse:
    del current_user
    require_csrf(request)
    clear_auth_cookies(response)
    return MessageResponse(message="Logged out successfully")
