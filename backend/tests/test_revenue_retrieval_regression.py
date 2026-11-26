"""Regression coverage for focused revenue evidence, retrieval, and citations."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Document, DocumentPage, DocumentStatus, User
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalResult,
    RetrievalDiagnostics,
    RetrievalStrategy,
)
from app.services.evidence_page_selector import EvidencePageSelector
from app.services.llm_service import LLMResult
from app.services.rag_pipeline import ABSTENTION_ANSWER, RagPipeline
from app.services.retrieval_service import SemanticRetrievalService
from app.services.vector_store import VectorSearchResult
from app.utils.security import hash_password

pytestmark = pytest.mark.anyio

PAGE_1 = """NORTHSTAR OFFICE SUPPLIES LTD.
Illustrative Annual Financial Report
Reporting currency: Indian rupees (INR). Amounts are shown in I lakh.
Page 1"""
PAGE_2 = """1. Management overview
During 2025, Northstar Office Supplies Ltd. recorded revenue of I1,250 lakh,
compared with I1,100 lakh in 2024.
2. Income statement (I lakh)
Revenue from operations
1,250
1,100
Page 2"""
PAGE_4 = """5. Selected financial ratios
Gross profit margin 32.0%
Gross profit divided by revenue
Return on sales 8.4%
Profit after tax divided by revenue
Page 4"""
PAGE_5 = """Suggested questions to ask FinAssist AI
What was revenue from operations in 2025?
By what percentage did revenue grow from 2024 to 2025?
Page 5"""


class StaticRetrieval:
    def __init__(self, results: list[VectorSearchResult]) -> None:
        self.results = results

    async def retrieve(self, db, question, *, user_id, document_ids, top_k):
        del db, question, document_ids, top_k
        selected = [item for item in self.results if item.user_id == user_id]
        return AdaptiveRetrievalResult(
            retrieved_chunks=selected,
            diagnostics=RetrievalDiagnostics(
                selected_strategy=RetrievalStrategy.KEYWORD,
                selection_reason="Test exact financial retrieval.",
                query_analysis={"query_type": "financial_metric"},
                keyword_result_count=len(selected),
                semantic_result_count=0,
                fusion_result_count=0,
                retrieved_chunks_count=len(selected),
                retrieval_time_ms=1.0,
            ),
            component_rankings={
                "keyword": [item.chunk_id for item in selected],
                "semantic": [],
                "fusion": [],
            },
        )


class FocusedRevenueLLM:
    model_name = "focused-test-llm"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResult:
        del system_prompt
        self.calls.append(user_prompt)
        assert "Pages: 2" in user_prompt
        assert "₹1,250 lakh" in user_prompt
        assert "Suggested questions" not in user_prompt
        return LLMResult(
            answer="The company's total revenue was ₹1,250 lakh in 2025 [Source 1].",
            model_name=self.model_name,
        )


class NeverCalledLLM:
    model_name = "never-called"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResult:
        del system_prompt, user_prompt
        self.calls += 1
        raise AssertionError("unsupported evidence must abstain before generation")


async def _indexed_sample(session_factory):
    user = User(
        full_name="Revenue Regression",
        email=f"{uuid4()}@example.com",
        hashed_password=hash_password("SecureRevenueRegression123!"),
    )
    document = Document(
        user=user,
        filename="finassist_sample_financial_report.pdf",
        storage_path="private/sample.pdf",
        file_size=4096,
        mime_type="application/pdf",
        page_count=5,
        processing_status=DocumentStatus.COMPLETED,
        indexed_chunk_count=3,
        indexed_at=datetime.now(UTC),
    )
    document.pages = [
        DocumentPage(page_number=1, extracted_text=PAGE_1, char_count=len(PAGE_1)),
        DocumentPage(page_number=2, extracted_text=PAGE_2, char_count=len(PAGE_2)),
        DocumentPage(page_number=4, extracted_text=PAGE_4, char_count=len(PAGE_4)),
        DocumentPage(page_number=5, extracted_text=PAGE_5, char_count=len(PAGE_5)),
    ]
    async with session_factory() as db:
        db.add(user)
        await db.commit()
        return user.id, document.id


def _retrieved_chunks(user_id, document_id):
    return [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="finassist_sample_financial_report.pdf",
            page_numbers=[1, 2, 3],
            chunk_text=f"{PAGE_1}\n{PAGE_2}",
            similarity_score=0.13,
        ),
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="finassist_sample_financial_report.pdf",
            page_numbers=[2, 3, 4, 5],
            chunk_text=f"{PAGE_4}\n{PAGE_5}",
            similarity_score=0.12,
        ),
    ]


@pytest.mark.parametrize(
    "question",
    [
        "What was the company's total revenue in the financial report? Give the figure and cite the page.",
        "What was revenue from operations in 2025?",
        "What was the company's total revenue?",
    ],
)
async def test_revenue_wording_selects_actual_page_two(
    session_factory: async_sessionmaker[AsyncSession], question: str
) -> None:
    user_id, document_id = await _indexed_sample(session_factory)
    chunks = _retrieved_chunks(user_id, document_id)

    async with session_factory() as db:
        selected = await EvidencePageSelector().refine(
            db,
            question,
            chunks,
            user_id=user_id,
            allowed_document_ids={document_id},
        )

    assert len(selected) == 1
    assert selected[0].chunk_id == chunks[0].chunk_id
    assert selected[0].page_numbers == [2]
    assert "₹1,250 lakh" in selected[0].chunk_text
    assert "Revenue from operations" in selected[0].chunk_text


async def test_exact_revenue_answer_is_verified_with_page_two_citation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await _indexed_sample(session_factory)
    llm = FocusedRevenueLLM()
    pipeline = RagPipeline(
        StaticRetrieval(_retrieved_chunks(user_id, document_id)), llm
    )

    async with session_factory() as db:
        answer = await pipeline.answer(
            db,
            user_id=user_id,
            question="What was the company's total revenue in the financial report? Give the figure and cite the page.",
            document_ids=[document_id],
        )

    assert answer.answer == (
        "The company's total revenue was ₹1,250 lakh in 2025 [Source 1]."
    )
    assert answer.verification.overall_status == "verified"
    assert answer.sources[0].page_numbers == [2]
    assert answer.sources[0].filename == "finassist_sample_financial_report.pdf"
    assert llm.calls


async def test_unsupported_metric_still_abstains(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await _indexed_sample(session_factory)
    llm = NeverCalledLLM()
    pipeline = RagPipeline(
        StaticRetrieval(_retrieved_chunks(user_id, document_id)),
        llm,
        maximum_retrieval_attempts=0,
    )

    async with session_factory() as db:
        answer = await pipeline.answer(
            db,
            user_id=user_id,
            question="What was EBITDA in 2025?",
            document_ids=[document_id],
        )

    assert answer.answer == ABSTENTION_ANSWER
    assert answer.sources == []
    assert answer.verification.overall_status == "abstained"
    assert llm.calls == 0


def test_semantic_retrieval_keeps_relevant_indexed_evidence() -> None:
    user_id = uuid4()
    document_id = uuid4()
    relevant = VectorSearchResult(
        chunk_id=uuid4(),
        user_id=user_id,
        document_id=document_id,
        filename="finassist_sample_financial_report.pdf",
        page_numbers=[2],
        chunk_text="Revenue from operations was ₹1,250 lakh in 2025.",
        similarity_score=0.81,
    )

    class Embeddings:
        def embed_query(self, question):
            assert "total revenue" in question
            return [1.0, 0.0]

    class Store:
        def search_similar_chunks(self, query_embedding, **kwargs):
            assert query_embedding == [1.0, 0.0]
            assert kwargs["user_id"] == user_id
            assert kwargs["document_ids"] == [document_id]
            return [relevant]

    service = SemanticRetrievalService(Embeddings(), Store(), minimum_similarity=0.25)
    results = service.retrieve(
        "What was total revenue?", user_id=user_id, document_ids=[document_id]
    )

    assert results == [relevant]
