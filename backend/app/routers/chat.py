"""Authenticated adaptive RAG chat and conversation history APIs."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser
from app.models.chat import ChatMessage, ChatRole, ChatSession
from app.schemas.chat import (
    ChatAskRequest,
    ChatAskResponse,
    ChatMessageResponse,
    ChatSessionDetail,
    ChatSessionListResponse,
    ChatSessionSummary,
    ChatSource,
)
from app.services.embedding_service import EmbeddingServiceError
from app.services.evidence_verifier import VerificationServiceError
from app.services.llm_service import LLMServiceError, LLMTimeoutError
from app.services.rag_dependencies import get_rag_pipeline
from app.services.rag_pipeline import (
    NoIndexedDocumentsError,
    RagAccessError,
    RagPipeline,
)
from app.services.vector_store import VectorStoreError
from app.utils.security import require_csrf

router = APIRouter(prefix="/chat", tags=["chat"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
Pipeline = Annotated[RagPipeline, Depends(get_rag_pipeline)]


async def _owned_session(
    db: AsyncSession, session_id: UUID, user_id: UUID
) -> ChatSession:
    session = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.post("/ask", response_model=ChatAskResponse)
async def ask_question(
    payload: ChatAskRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    pipeline: Pipeline,
) -> ChatAskResponse:
    require_csrf(request)
    session = (
        await _owned_session(db, payload.session_id, current_user.id)
        if payload.session_id
        else None
    )
    try:
        result = await pipeline.answer(
            db,
            user_id=current_user.id,
            question=payload.question,
            document_ids=payload.document_ids,
        )
    except RagAccessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoIndexedDocumentsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (
        EmbeddingServiceError,
        LLMServiceError,
        VectorStoreError,
        VerificationServiceError,
    ) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if session is None:
        session = ChatSession(
            user_id=current_user.id,
            title=payload.question[:80].strip() or "New conversation",
        )
        db.add(session)
        await db.flush()

    source_values = [source.json_dict() for source in result.sources]
    message_time = datetime.now(UTC)
    db.add_all(
        [
            ChatMessage(
                session_id=session.id,
                role=ChatRole.USER,
                message=payload.question,
                sources=[],
                created_at=message_time,
            ),
            ChatMessage(
                session_id=session.id,
                role=ChatRole.ASSISTANT,
                message=result.answer,
                sources=source_values,
                model_name=result.model_name,
                retrieved_chunks_count=result.retrieved_chunks_count,
                retrieval_time_ms=result.retrieval_time_ms,
                generation_time_ms=result.generation_time_ms,
                retrieval=result.retrieval.as_dict(),
                evidence_status=result.verification.evidence_status.value,
                verification_status=result.verification.overall_status,
                confidence_score=result.confidence.score,
                verification_metadata=result.verification.as_dict(),
                confidence_metadata=result.confidence.as_dict(),
                retrieval_attempts=result.verification.retrieval_attempts,
                created_at=message_time + timedelta(microseconds=1),
            ),
        ]
    )
    await db.commit()
    return ChatAskResponse(
        session_id=session.id,
        answer=result.answer,
        sources=[ChatSource.model_validate(value) for value in source_values],
        retrieved_chunks_count=result.retrieved_chunks_count,
        model_name=result.model_name,
        retrieval_time_ms=result.retrieval_time_ms,
        generation_time_ms=result.generation_time_ms,
        usage=result.usage,
        retrieval=result.retrieval.as_dict(),
        verification=result.verification.as_dict(),
        confidence=result.confidence.as_dict(),
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    current_user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChatSessionListResponse:
    total = (
        await db.scalar(
            select(func.count(ChatSession.id)).where(
                ChatSession.user_id == current_user.id
            )
        )
        or 0
    )
    message_count = (
        select(func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(ChatSession, message_count.label("message_count"))
            .where(ChatSession.user_id == current_user.id)
            .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ChatSessionListResponse(
        items=[
            ChatSessionSummary(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                message_count=count,
            )
            for session, count in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=((total + page_size - 1) // page_size) if total else 0,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    session_id: UUID, current_user: CurrentUser, db: DbSession
) -> ChatSessionDetail:
    session = await _owned_session(db, session_id, current_user.id)
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        messages=[ChatMessageResponse.model_validate(message) for message in messages],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    require_csrf(request)
    session = await _owned_session(db, session_id, current_user.id)
    await db.delete(session)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
