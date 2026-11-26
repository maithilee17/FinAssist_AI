"""Isolated database and HTTP client fixtures for backend tests."""

import os
import tempfile
from collections.abc import AsyncIterator
from math import sqrt
from pathlib import Path
from uuid import UUID

# Application routers construct private storage during import. Keep that import-time
# path isolated from a developer's Docker-oriented UPLOAD_DIR in the root .env file.
os.environ["UPLOAD_DIR"] = str(Path(tempfile.gettempdir()) / "finassist-test-uploads")

os.environ["LLM_PROVIDER"] = "ollama"

import httpx
import pymupdf
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ChatMessage, ChatSession, Document, User  # noqa: F401
from app.routers.documents import get_document_storage
from app.services.rag_dependencies import get_embedding_service, get_vector_store
from app.services.storage_service import PrivateDocumentStorage
from app.services.vector_store import VectorChunk, VectorSearchResult


class FakeEmbeddingService:
    model_name = "test-financial-embedding"

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        values = [
            float(lowered.count("revenue") + lowered.count("sales")),
            float(lowered.count("profit") + lowered.count("income")),
            float(lowered.count("asset") + lowered.count("liabilit")),
            float(max(1, len(lowered.split()))),
        ]
        norm = sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def embed_documents(self, texts) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, question: str) -> list[float]:
        return self._vector(question)


class FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[UUID, tuple[VectorChunk, list[float]]] = {}

    def add_chunks(self, chunks, embeddings) -> int:
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self.records[chunk.id] = (chunk, list(embedding))
        return len(chunks)

    def search_similar_chunks(
        self, query_embedding, *, user_id, document_ids=None, top_k=5
    ) -> list[VectorSearchResult]:
        selected = set(document_ids or [])
        results = []
        for chunk, embedding in self.records.values():
            if chunk.user_id != user_id or (
                selected and chunk.document_id not in selected
            ):
                continue
            score = sum(a * b for a, b in zip(query_embedding, embedding, strict=True))
            results.append(
                VectorSearchResult(
                    chunk_id=chunk.id,
                    user_id=chunk.user_id,
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    page_numbers=chunk.page_numbers,
                    chunk_text=chunk.text,
                    similarity_score=score,
                    section=chunk.section,
                )
            )
        return sorted(results, key=lambda item: item.similarity_score, reverse=True)[
            :top_k
        ]

    def count_document_chunks(self, user_id, document_id) -> int:
        return sum(
            chunk.user_id == user_id and chunk.document_id == document_id
            for chunk, _ in self.records.values()
        )

    def delete_document_chunks(self, user_id, document_id) -> None:
        self.records = {
            key: value
            for key, value in self.records.items()
            if not (value[0].user_id == user_id and value[0].document_id == document_id)
        }

    def delete_user_chunks(self, user_id) -> None:
        self.records = {
            key: value
            for key, value in self.records.items()
            if value[0].user_id != user_id
        }

    def health_check(self) -> bool:
        return True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def test_engine() -> AsyncIterator[AsyncEngine]:
    test_database_url = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    if (
        not test_database_url.startswith("sqlite")
        and "test" not in test_database_url.lower()
    ):
        raise RuntimeError("TEST_DATABASE_URL must identify an explicit test database")

    engine_options = {}
    if test_database_url == "sqlite+aiosqlite:///:memory:":
        engine_options = {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        }
    engine = create_async_engine(test_database_url, **engine_options)

    if test_database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def session_factory(test_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
def private_storage(tmp_path) -> PrivateDocumentStorage:
    return PrivateDocumentStorage(
        tmp_path / "private-uploads",
        max_size_bytes=5 * 1024 * 1024,
        read_chunk_bytes=64 * 1024,
    )


@pytest.fixture
def fake_embedding_service() -> FakeEmbeddingService:
    return FakeEmbeddingService()


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture
def pdf_bytes_factory():
    def build(pages: list[str]) -> bytes:
        document = pymupdf.open()
        for text in pages:
            page = document.new_page()
            if text:
                page.insert_htmlbox(
                    pymupdf.Rect(50, 50, 545, 790),
                    f"<div style='font-family: sans-serif; font-size: 12pt'>{text}</div>",
                )
        content = document.tobytes()
        document.close()
        return content

    return build


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    private_storage: PrivateDocumentStorage,
    fake_embedding_service: FakeEmbeddingService,
    fake_vector_store: FakeVectorStore,
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = lambda: private_storage
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service
    app.dependency_overrides[get_vector_store] = lambda: fake_vector_store
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
