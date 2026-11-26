"""Liveness and dependency readiness endpoints."""

import asyncio
from typing import Literal

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.services.llm_service import LLMServiceError, create_llm_service

router = APIRouter(prefix="/health", tags=["health"])
settings = get_settings()


class DependencyHealth(BaseModel):
    status: Literal["up", "down"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    services: dict[str, DependencyHealth]


async def check_postgres() -> DependencyHealth:
    try:
        async with asyncio.timeout(settings.database_connect_timeout_seconds + 1):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return DependencyHealth(status="up")
    except Exception as exc:  # noqa: BLE001 - readiness must collapse all driver failures.
        return DependencyHealth(status="down", detail=type(exc).__name__)


async def check_chroma() -> DependencyHealth:
    try:
        async with httpx.AsyncClient(timeout=settings.chroma_timeout_seconds) as client:
            response = await client.get(f"{settings.chroma_base_url}/api/v2/heartbeat")
            response.raise_for_status()
        return DependencyHealth(status="up")
    except Exception as exc:  # noqa: BLE001 - readiness must collapse all client failures.
        return DependencyHealth(status="down", detail=type(exc).__name__)


async def check_ollama() -> DependencyHealth:
    try:
        await create_llm_service(settings).check_health()
        return DependencyHealth(status="up")
    except LLMServiceError as exc:
        return DependencyHealth(status="down", detail=str(exc))


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {
        "status": "alive",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> JSONResponse:
    postgres, chroma, ollama = await asyncio.gather(
        check_postgres(), check_chroma(), check_ollama()
    )
    services = {"postgres": postgres, "chroma": chroma, "ollama": ollama}
    is_ready = all(service.status == "up" for service in services.values())
    payload = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        services=services,
    )
    return JSONResponse(
        status_code=200 if is_ready else 503, content=payload.model_dump()
    )
