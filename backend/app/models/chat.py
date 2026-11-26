"""Conversation session and message models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(back_populates="chat_sessions")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ChatRole] = mapped_column(
        SqlEnum(
            ChatRole,
            name="chat_role",
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        )
    )
    message: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    model_name: Mapped[str | None] = mapped_column(String(255))
    retrieved_chunks_count: Mapped[int | None] = mapped_column(Integer)
    retrieval_time_ms: Mapped[float | None] = mapped_column(Float)
    generation_time_ms: Mapped[float | None] = mapped_column(Float)
    retrieval: Mapped[dict[str, object] | None] = mapped_column(JSON)
    evidence_status: Mapped[str | None] = mapped_column(String(32))
    verification_status: Mapped[str | None] = mapped_column(String(32))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    verification_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    confidence_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    retrieval_attempts: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")
