"""BM25 relevance, filtering, isolation, and cache invalidation tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Document, DocumentChunk, DocumentStatus, User
from app.services.keyword_retrieval import (
    KeywordRetrievalService,
    tokenize_financial_text,
)
from app.utils.security import hash_password

pytestmark = pytest.mark.anyio


def test_financial_tokenizer_preserves_signed_parenthetical_and_currency_values() -> (
    None
):
    tokens = tokenize_financial_text(
        "Loss was ($1,250.50) and margin was -4.2% in FY2025"
    )
    assert "$" in tokens
    assert "-1250.50" in tokens
    assert "-4.2%" in tokens
    assert "fy2025" in tokens


def test_financial_tokenizer_removes_question_stopwords() -> None:
    tokens = tokenize_financial_text("What was revenue in fiscal 2025?")
    assert "what" not in tokens
    assert "was" not in tokens
    assert "in" not in tokens
    assert "revenue" in tokens
    assert "2025" in tokens


async def add_corpus(session_factory, email, chunks):
    user_id = uuid4()
    user = User(
        id=user_id,
        full_name="Keyword Tester",
        email=email,
        hashed_password=hash_password("SecureKeywordTester123!"),
    )
    document = Document(
        user=user,
        filename=f"{email}.pdf",
        storage_path=f"private/{email}.pdf",
        file_size=1000,
        mime_type="application/pdf",
        page_count=len(chunks),
        processing_status=DocumentStatus.COMPLETED,
        indexed_chunk_count=len(chunks),
        indexed_at=datetime.now(UTC),
    )
    for index, text in enumerate(chunks):
        document.chunks.append(
            DocumentChunk(
                id=uuid4(),
                user_id=user_id,
                chunk_index=index,
                text=text,
                token_count=len(text.split()),
                page_numbers=[index + 1],
            )
        )
    async with session_factory() as db:
        db.add(user)
        await db.commit()
        return user.id, document.id


async def test_keyword_retrieval_finds_exact_financial_terms_and_reuses_cache(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _ = await add_corpus(
        session_factory,
        "keyword@example.com",
        [
            "FY2025 revenue was ₹1,250.50 million.",
            "Operational challenges affected overseas distribution.",
        ],
    )
    service = KeywordRetrievalService()
    async with session_factory() as db:
        first = await service.search_keyword("FY2025 revenue", user_id, db=db)
        second = await service.search_keyword("₹1,250.50", user_id, db=db)
    assert first[0].chunk_text.startswith("FY2025 revenue")
    assert second[0].page_numbers == [1]
    assert service.build_count == 1


async def test_keyword_retrieval_prioritizes_metric_and_period_over_boilerplate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _ = await add_corpus(
        session_factory,
        "keyword-ranking@example.com",
        [
            "NVIDIA fiscal 2025 annual report information for investors and filings.",
            "Fiscal 2025 operating income was $81,453 million.",
            "The company published general fiscal 2025 information.",
        ],
    )
    service = KeywordRetrievalService()
    async with session_factory() as db:
        results = await service.search_keyword(
            "What was NVIDIA's operating income in fiscal 2025?", user_id, db=db
        )
    assert results[0].page_numbers == [2]


async def test_keyword_retrieval_enforces_user_and_document_filters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_user, first_document = await add_corpus(
        session_factory, "first-keyword@example.com", ["UniqueAlpha revenue FY2025"]
    )
    second_user, second_document = await add_corpus(
        session_factory, "second-keyword@example.com", ["UniqueBeta revenue FY2025"]
    )
    service = KeywordRetrievalService()
    async with session_factory() as db:
        isolated = await service.search_keyword("UniqueBeta", first_user, db=db)
        excluded = await service.search_keyword(
            "UniqueAlpha", first_user, [second_document], db=db
        )
        selected = await service.search_keyword(
            "UniqueAlpha", first_user, [first_document], db=db
        )
        owner = await service.search_keyword("UniqueBeta", second_user, db=db)
    assert isolated == []
    assert excluded == []
    assert len(selected) == len(owner) == 1


async def test_empty_corpus_and_cache_invalidation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = KeywordRetrievalService()
    empty_user = uuid4()
    async with session_factory() as db:
        assert await service.search_keyword("revenue", empty_user, db=db) == []
        assert await service.search_keyword("revenue", empty_user, db=db) == []
        assert service.build_count == 1
        service.invalidate_user(empty_user)
        assert await service.search_keyword("revenue", empty_user, db=db) == []
    assert service.build_count == 2
