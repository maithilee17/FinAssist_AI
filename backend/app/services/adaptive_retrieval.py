"""Rule-based strategy selection and keyword/semantic/hybrid orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.services.keyword_retrieval import KeywordRetrievalService
from app.services.query_analyzer import FinancialQueryAnalyzer, QueryAnalysis, QueryType
from app.services.rank_fusion import reciprocal_rank_fusion
from app.services.retrieval_service import SemanticRetrievalService
from app.services.vector_store import VectorSearchResult

logger = logging.getLogger(__name__)


class RetrievalStrategy(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class StrategySelection:
    selected_strategy: RetrievalStrategy
    reason: str
    query_analysis: QueryAnalysis


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    selected_strategy: RetrievalStrategy
    selection_reason: str
    query_analysis: dict[str, object]
    keyword_result_count: int
    semantic_result_count: int
    fusion_result_count: int
    retrieved_chunks_count: int
    retrieval_time_ms: float

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["selected_strategy"] = self.selected_strategy.value
        return values


@dataclass(frozen=True, slots=True)
class AdaptiveRetrievalResult:
    retrieved_chunks: list[VectorSearchResult]
    diagnostics: RetrievalDiagnostics
    component_rankings: dict[str, list[UUID]]


class AdaptiveRetrievalSelector:
    def __init__(self, *, exact_term_threshold: int = 1) -> None:
        self.exact_term_threshold = exact_term_threshold

    def select(self, analysis: QueryAnalysis) -> StrategySelection:
        if analysis.query_type == QueryType.CALCULATION:
            return StrategySelection(
                RetrievalStrategy.HYBRID,
                "Financial calculation requires input figures and contextual retrieval; fusion executed.",
                analysis,
            )
        if analysis.has_comparison:
            return StrategySelection(
                RetrievalStrategy.HYBRID,
                "The query compares financial values, periods, or conditions and benefits from exact and contextual retrieval.",
                analysis,
            )
        if analysis.requires_semantic_context and analysis.has_exact_terms:
            return StrategySelection(
                RetrievalStrategy.HYBRID,
                "The query mixes specific financial terminology with a request for contextual explanation.",
                analysis,
            )
        if analysis.query_type in {QueryType.CONCEPTUAL, QueryType.DESCRIPTIVE}:
            return StrategySelection(
                RetrievalStrategy.SEMANTIC,
                "The query is conceptual or descriptive and may use wording different from the document.",
                analysis,
            )
        if (
            analysis.query_type
            in {
                QueryType.EXACT_FACT,
                QueryType.FINANCIAL_METRIC,
                QueryType.REGULATORY,
            }
            or analysis.exact_signal_count >= self.exact_term_threshold
        ):
            return StrategySelection(
                RetrievalStrategy.KEYWORD,
                "The query contains exact financial terms, identifiers, figures, dates, or reporting periods.",
                analysis,
            )
        return StrategySelection(
            RetrievalStrategy.SEMANTIC,
            "The query has no strong exact-match signals, so semantic retrieval is preferred.",
            analysis,
        )


class AdaptiveRetrievalService:
    def __init__(
        self,
        keyword_service: KeywordRetrievalService,
        semantic_service: SemanticRetrievalService,
        *,
        analyzer: FinancialQueryAnalyzer | None = None,
        selector: AdaptiveRetrievalSelector | None = None,
        default_top_k: int = 5,
        rrf_constant: int = 60,
    ) -> None:
        self.keyword_service = keyword_service
        self.semantic_service = semantic_service
        self.analyzer = analyzer or FinancialQueryAnalyzer()
        self.selector = selector or AdaptiveRetrievalSelector()
        self.default_top_k = default_top_k
        self.rrf_constant = rrf_constant

    async def retrieve(
        self,
        db: AsyncSession,
        question: str,
        *,
        user_id: UUID,
        document_ids: Sequence[UUID] | None = None,
        top_k: int | None = None,
        force_strategy: RetrievalStrategy | None = None,
    ) -> AdaptiveRetrievalResult:
        limit = top_k or self.default_top_k
        analysis = self.analyzer.analyze(question)
        selection = self.selector.select(analysis)
        if force_strategy is not None:
            selection = StrategySelection(
                force_strategy,
                f"Strategy forced to {force_strategy.value} for evaluation.",
                analysis,
            )
        started = perf_counter()
        keyword_results: list[VectorSearchResult] = []
        semantic_results: list[VectorSearchResult] = []
        fused_results: list[VectorSearchResult] = []

        async def keyword_search() -> list[VectorSearchResult]:
            return await self.keyword_service.search_keyword(
                question,
                user_id,
                document_ids,
                limit,
                db=db,
            )

        async def semantic_search() -> list[VectorSearchResult]:
            return await run_in_threadpool(
                self.semantic_service.retrieve,
                question,
                user_id=user_id,
                document_ids=document_ids,
                top_k=limit,
            )

        if selection.selected_strategy == RetrievalStrategy.KEYWORD:
            keyword_results = await keyword_search()
            selected = keyword_results
        elif selection.selected_strategy == RetrievalStrategy.SEMANTIC:
            semantic_results = await semantic_search()
            selected = semantic_results
        else:
            keyword_results, semantic_results = await asyncio.gather(
                keyword_search(), semantic_search()
            )
            fused = reciprocal_rank_fusion(
                {"keyword": keyword_results, "semantic": semantic_results},
                rrf_constant=self.rrf_constant,
                top_k=limit,
            )
            fused_results = [item.result for item in fused]
            selected = fused_results

        retrieval_time_ms = (perf_counter() - started) * 1000
        logger.info(
            "Adaptive retrieval strategy=%s reason=%s user_id=%s",
            selection.selected_strategy.value,
            selection.reason,
            user_id,
        )
        diagnostics = RetrievalDiagnostics(
            selected_strategy=selection.selected_strategy,
            selection_reason=selection.reason,
            query_analysis=analysis.as_dict(),
            keyword_result_count=len(keyword_results),
            semantic_result_count=len(semantic_results),
            fusion_result_count=len(fused_results),
            retrieved_chunks_count=len(selected),
            retrieval_time_ms=round(retrieval_time_ms, 3),
        )
        return AdaptiveRetrievalResult(
            retrieved_chunks=selected,
            diagnostics=diagnostics,
            component_rankings={
                "keyword": [item.chunk_id for item in keyword_results],
                "semantic": [item.chunk_id for item in semantic_results],
                "fusion": [item.chunk_id for item in fused_results],
            },
        )
