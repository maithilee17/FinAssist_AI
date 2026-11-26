"""Reciprocal Rank Fusion correctness and deterministic behavior tests."""

from uuid import uuid4

import pytest

from app.services.rank_fusion import reciprocal_rank_fusion
from app.services.vector_store import VectorSearchResult


def result(chunk_id, score, text="evidence") -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        user_id=uuid4(),
        document_id=uuid4(),
        filename="report.pdf",
        page_numbers=[7],
        chunk_text=text,
        similarity_score=score,
    )


def test_rrf_combines_ranks_without_mixing_score_scales() -> None:
    shared, keyword_only, semantic_only = uuid4(), uuid4(), uuid4()
    fused = reciprocal_rank_fusion(
        {
            "keyword": [result(shared, 19.4), result(keyword_only, 3.1)],
            "semantic": [result(semantic_only, 0.93), result(shared, 0.81)],
        },
        rrf_constant=60,
    )
    assert fused[0].result.chunk_id == shared
    assert fused[0].rrf_score == pytest.approx(1 / 61 + 1 / 62)
    assert fused[0].component_ranks == {"keyword": 1, "semantic": 2}
    assert fused[0].component_scores == {"keyword": 19.4, "semantic": 0.81}


def test_rrf_deduplicates_each_ranking_and_preserves_metadata() -> None:
    chunk_id = uuid4()
    original = result(chunk_id, 4.0, "FY2025 revenue evidence")
    fused = reciprocal_rank_fusion(
        {"keyword": [original, original], "semantic": []}, rrf_constant=60
    )
    assert len(fused) == 1
    assert fused[0].rrf_score == pytest.approx(1 / 61)
    assert fused[0].result.chunk_text == "FY2025 revenue evidence"
    assert fused[0].result.page_numbers == [7]


def test_rrf_preserves_keyword_results_when_semantic_results_are_empty() -> None:
    chunk_id = uuid4()
    keyword = result(chunk_id, 4.2, "Revenue from operations was ₹1,250 lakh.")

    fused = reciprocal_rank_fusion(
        {"keyword": [keyword], "semantic": []}, rrf_constant=60, top_k=5
    )

    assert len(fused) == 1
    assert fused[0].result.chunk_id == chunk_id
    assert fused[0].component_ranks == {"keyword": 1}


def test_rrf_ties_are_stable_and_limit_is_applied() -> None:
    first_id, second_id = sorted([uuid4(), uuid4()], key=str)
    fused = reciprocal_rank_fusion(
        {
            "keyword": [result(first_id, 1.0)],
            "semantic": [result(second_id, 1.0)],
        },
        top_k=1,
    )
    assert [item.result.chunk_id for item in fused] == [first_id]


def test_rrf_rejects_invalid_constant() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({}, rrf_constant=0)
