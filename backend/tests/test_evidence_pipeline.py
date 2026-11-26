"""Bounded retrieve-more, deduplication, revision, and ownership integration tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Document, DocumentStatus, User
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalResult,
    RetrievalDiagnostics,
    RetrievalStrategy,
)
from app.services.evidence_verifier import VerificationServiceError
from app.services.llm_service import LLMResult
from app.services.rag_pipeline import ABSTENTION_ANSWER, RagPipeline
from app.services.vector_store import VectorSearchResult
from app.utils.security import hash_password

pytestmark = pytest.mark.anyio


class StagedRetrieval:
    def __init__(self, initial, expanded=None):
        self.initial = initial
        self.expanded = expanded if expanded is not None else initial
        self.top_k_calls = []

    async def retrieve(self, db, question, *, user_id, document_ids, top_k):
        del db, question, user_id, document_ids
        self.top_k_calls.append(top_k)
        values = self.initial if len(self.top_k_calls) == 1 else self.expanded
        return AdaptiveRetrievalResult(
            retrieved_chunks=values[:top_k],
            diagnostics=RetrievalDiagnostics(
                selected_strategy=RetrievalStrategy.HYBRID,
                selection_reason="Test routing.",
                query_analysis={"query_type": "comparison"},
                keyword_result_count=len(values),
                semantic_result_count=len(values),
                fusion_result_count=len(values),
                retrieved_chunks_count=min(top_k, len(values)),
                retrieval_time_ms=2.0,
            ),
            component_rankings={"keyword": [], "semantic": [], "fusion": []},
        )


class EvidenceLLM:
    model_name = "evidence-test-llm"

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def generate(self, system_prompt, user_prompt):
        self.calls += 1
        assert "Every factual claim must be supported" in system_prompt
        assert "<evidence>" in user_prompt
        return LLMResult(answer=self.answer, model_name=self.model_name)


async def indexed_owner(session_factory):
    user = User(
        full_name="Evidence Tester",
        email=f"{uuid4()}@example.com",
        hashed_password=hash_password("SecureEvidenceTester123!"),
    )
    document = Document(
        user=user,
        filename="annual-report.pdf",
        storage_path="private/report.pdf",
        file_size=1000,
        mime_type="application/pdf",
        page_count=10,
        processing_status=DocumentStatus.COMPLETED,
        indexed_chunk_count=2,
        indexed_at=datetime.now(UTC),
    )
    async with session_factory() as db:
        db.add(user)
        await db.commit()
        return user.id, document.id


def result(user_id, document_id, text, page, chunk_id=None):
    return VectorSearchResult(
        chunk_id=chunk_id or uuid4(),
        user_id=user_id,
        document_id=document_id,
        filename="annual-report.pdf",
        page_numbers=[page],
        chunk_text=text,
        similarity_score=0.9,
    )


async def test_weak_evidence_expands_and_deduplicates_before_generation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await indexed_owner(session_factory)
    current = result(user_id, document_id, "FY2025 revenue was $1.25 billion.", 5)
    previous = result(user_id, document_id, "FY2024 revenue was $1.10 billion.", 4)
    retrieval = StagedRetrieval([current], [current, current, previous])
    llm = EvidenceLLM(
        "FY2024 revenue was $1.10 billion [Source 2]. FY2025 revenue was $1.25 billion [Source 1]."
    )
    pipeline = RagPipeline(retrieval, llm)
    async with session_factory() as db:
        answer = await pipeline.answer(
            db,
            user_id=user_id,
            question="Compare revenue in FY2024 and FY2025.",
        )
    assert retrieval.top_k_calls == [5, 10]
    assert answer.verification.retrieval_attempts == 2
    assert answer.verification.overall_status == "verified"
    assert answer.retrieved_chunks_count == 2
    assert llm.calls == 1


async def test_sufficient_evidence_does_not_trigger_extra_retrieval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await indexed_owner(session_factory)
    item = result(user_id, document_id, "FY2025 revenue was $1.25 billion.", 5)
    retrieval = StagedRetrieval([item])
    llm = EvidenceLLM("FY2025 revenue was $1.25 billion [Source 1].")
    pipeline = RagPipeline(retrieval, llm)
    async with session_factory() as db:
        answer = await pipeline.answer(
            db, user_id=user_id, question="What was FY2025 revenue?"
        )
    assert retrieval.top_k_calls == [5]
    assert answer.verification.retrieval_attempts == 1
    assert answer.verification.overall_status == "verified"


async def test_retrieve_more_stops_at_configured_limit_and_abstains(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await indexed_owner(session_factory)
    item = result(user_id, document_id, "FY2025 revenue was $1.25 billion.", 5)
    retrieval = StagedRetrieval([item])
    llm = EvidenceLLM("This must not be generated.")
    pipeline = RagPipeline(
        retrieval,
        llm,
        maximum_top_k=15,
        maximum_retrieval_attempts=2,
    )
    async with session_factory() as db:
        answer = await pipeline.answer(
            db,
            user_id=user_id,
            question="Compare revenue in FY2024 and FY2025.",
        )
    assert retrieval.top_k_calls == [5, 10, 15]
    assert answer.answer == ABSTENTION_ANSWER
    assert answer.sources == []
    assert answer.verification.overall_status == "abstained"
    assert "2024 revenue" in answer.verification.missing_aspects
    assert llm.calls == 0


async def test_cross_user_retrieval_result_is_rejected_by_verifier(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await indexed_owner(session_factory)
    foreign = result(uuid4(), document_id, "FY2025 revenue was $1.25 billion.", 5)
    retrieval = StagedRetrieval([foreign])
    llm = EvidenceLLM("This must not be generated.")
    pipeline = RagPipeline(retrieval, llm)
    async with session_factory() as db:
        answer = await pipeline.answer(
            db, user_id=user_id, question="What was FY2025 revenue?"
        )
    assert answer.answer == ABSTENTION_ANSWER
    assert answer.sources == []
    assert llm.calls == 0


async def test_unsupported_claim_is_removed_without_second_llm_call(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, document_id = await indexed_owner(session_factory)
    item = result(user_id, document_id, "FY2025 revenue was $1.25 billion.", 5)
    retrieval = StagedRetrieval([item])
    llm = EvidenceLLM(
        "FY2025 revenue was $1.25 billion [Source 1]. Net profit fell by 4% [Source 1]."
    )
    pipeline = RagPipeline(retrieval, llm, maximum_revision_attempts=1)
    async with session_factory() as db:
        answer = await pipeline.answer(
            db, user_id=user_id, question="What was FY2025 revenue?"
        )
    assert "revenue was $1.25 billion" in answer.answer
    assert "Net profit" not in answer.answer
    assert answer.verification.overall_status == "partially_supported"
    assert answer.verification.removed_claims == 1
    assert llm.calls == 1


async def test_verifier_failure_is_fail_closed_and_does_not_call_llm(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    class BrokenVerifier:
        def verify(self, *args, **kwargs):
            raise RuntimeError("internal details must not escape")

    user_id, document_id = await indexed_owner(session_factory)
    item = result(user_id, document_id, "FY2025 revenue was $1.25 billion.", 5)
    retrieval = StagedRetrieval([item])
    llm = EvidenceLLM("This must not be generated.")
    pipeline = RagPipeline(retrieval, llm, evidence_verifier=BrokenVerifier())
    async with session_factory() as db:
        with pytest.raises(
            VerificationServiceError, match="could not be completed safely"
        ):
            await pipeline.answer(
                db, user_id=user_id, question="What was FY2025 revenue?"
            )
    assert llm.calls == 0
