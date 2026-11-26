"""Database model structure and relationship tests."""

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import ChatMessage, ChatRole, ChatSession, Document, User
from app.utils.security import hash_password

pytestmark = pytest.mark.anyio


async def test_model_tables_are_created(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
    assert set(table_names) == {
        "users",
        "documents",
        "document_pages",
        "document_chunks",
        "chat_sessions",
        "chat_messages",
    }


async def test_foreign_key_relationships_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = User(
        full_name="Model Test",
        email="model@example.com",
        hashed_password=hash_password("SecureModel123!"),
    )
    document = Document(
        filename="annual-report.pdf",
        storage_path="private/report.pdf",
        file_size=1024,
        mime_type="application/pdf",
    )
    chat_session = ChatSession(title="Revenue review")
    message = ChatMessage(role=ChatRole.USER, message="What was revenue?")
    user.documents.append(document)
    user.chat_sessions.append(chat_session)
    chat_session.messages.append(message)

    async with session_factory() as session:
        session.add(user)
        await session.commit()
        user_id = user.id

    async with session_factory() as session:
        saved_document = await session.scalar(
            select(Document).where(Document.user_id == user_id)
        )
        saved_session = await session.scalar(
            select(ChatSession).where(ChatSession.user_id == user_id)
        )
        saved_message = await session.scalar(
            select(ChatMessage).where(ChatMessage.session_id == saved_session.id)
        )

    assert saved_document is not None
    assert saved_document.filename == "annual-report.pdf"
    assert saved_message is not None
    assert saved_message.role == ChatRole.USER
