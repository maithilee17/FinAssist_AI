"""SQLAlchemy engine, declarative base, and request-scoped sessions."""

from collections.abc import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base mapper shared by all application models and Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"timeout": settings.database_connect_timeout_seconds},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield one independent database session per request."""

    async with AsyncSessionLocal() as session:
        yield session


async def close_database() -> None:
    """Release pooled database connections during application shutdown."""

    await engine.dispose()
