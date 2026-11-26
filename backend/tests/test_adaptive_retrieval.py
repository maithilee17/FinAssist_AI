"""Strategy selection and adaptive orchestration unit tests."""

from uuid import uuid4

import pytest

from app.services.adaptive_retrieval import (
    AdaptiveRetrievalSelector,
    AdaptiveRetrievalService,
    RetrievalStrategy,
)
from app.services.query_analyzer import FinancialQueryAnalyzer
from app.services.vector_store import VectorSearchResult

pytestmark = pytest.mark.anyio


def make_result(chunk_id=None, *, score=0.9, text="evidence") -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id or uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        filename="annual-report.pdf",
        page_numbers=[42],
        chunk_text=text,
        similarity_score=score,
    )


class FakeKeyword:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    async def search_keyword(self, *args, **kwargs):
        self.calls += 1
        return self.results


class FakeSemantic:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    def retrieve(self, *args, **kwargs):
        self.calls += 1
        return self.results


def test_selector_routes_exact_conceptual_and_comparison_queries() -> None:
    analyzer = FinancialQueryAnalyzer()
    selector = AdaptiveRetrievalSelector()
    exact = selector.select(analyzer.analyze("What was revenue in FY2025?"))
    conceptual = selector.select(
        analyzer.analyze("Why did overseas expansion present challenges?")
    )
    comparison = selector.select(
        analyzer.analyze("Compare revenue between FY2024 and FY2025")
    )
    assert exact.selected_strategy == RetrievalStrategy.KEYWORD
    assert conceptual.selected_strategy == RetrievalStrategy.SEMANTIC
    assert comparison.selected_strategy == RetrievalStrategy.HYBRID
    assert "exact" in exact.reason.lower()
    assert "conceptual" in conceptual.reason.lower()
    assert "compares" in comparison.reason.lower()


async def test_hybrid_runs_both_systems_and_fuses_duplicate_chunk() -> None:
    shared = uuid4()
    keyword = make_result(shared, score=9.0, text="Shared cited evidence")
    semantic = make_result(shared, score=0.93, text="Shared cited evidence")
    keyword_service = FakeKeyword([keyword])
    semantic_service = FakeSemantic([semantic, make_result()])
    service = AdaptiveRetrievalService(keyword_service, semantic_service)

    result = await service.retrieve(
        object(),
        "Compare revenue between FY2024 and FY2025",
        user_id=keyword.user_id,
    )

    assert result.diagnostics.selected_strategy == RetrievalStrategy.HYBRID
    assert result.diagnostics.keyword_result_count == 1
    assert result.diagnostics.semantic_result_count == 2
    assert result.diagnostics.fusion_result_count == 2
    assert result.retrieved_chunks[0].chunk_id == shared
    assert result.retrieved_chunks[0].page_numbers == [42]
    assert keyword_service.calls == semantic_service.calls == 1


async def test_forced_strategy_executes_only_requested_retriever() -> None:
    keyword_service = FakeKeyword([make_result()])
    semantic_service = FakeSemantic([make_result()])
    service = AdaptiveRetrievalService(keyword_service, semantic_service)
    result = await service.retrieve(
        object(),
        "revenue",
        user_id=uuid4(),
        force_strategy=RetrievalStrategy.SEMANTIC,
    )
    assert result.diagnostics.selected_strategy == RetrievalStrategy.SEMANTIC
    assert result.diagnostics.selection_reason.startswith("Strategy forced")
    assert keyword_service.calls == 0
    assert semantic_service.calls == 1


async def test_keyword_strategy_keeps_results_when_fusion_is_not_executed() -> None:
    keyword = make_result(text="Revenue from operations was ₹1,250 lakh.")
    keyword_service = FakeKeyword([keyword])
    semantic_service = FakeSemantic([])
    service = AdaptiveRetrievalService(keyword_service, semantic_service)

    result = await service.retrieve(
        object(),
        "What was revenue in FY2025?",
        user_id=keyword.user_id,
    )

    assert result.diagnostics.selected_strategy == RetrievalStrategy.KEYWORD
    assert result.diagnostics.keyword_result_count == 1
    assert result.diagnostics.semantic_result_count == 0
    assert result.diagnostics.fusion_result_count == 0
    assert result.retrieved_chunks == [keyword]
