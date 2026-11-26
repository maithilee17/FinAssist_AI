"""Reciprocal Rank Fusion for heterogeneous retrieval rankings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.services.vector_store import VectorSearchResult


@dataclass(frozen=True, slots=True)
class FusedRankedChunk:
    result: VectorSearchResult
    rrf_score: float
    component_ranks: dict[str, int]
    component_scores: dict[str, float]


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[VectorSearchResult]],
    *,
    rrf_constant: int = 60,
    top_k: int | None = None,
) -> list[FusedRankedChunk]:
    if rrf_constant < 1:
        raise ValueError("RRF constant must be positive")
    scores: dict[UUID, float] = {}
    metadata: dict[UUID, VectorSearchResult] = {}
    component_ranks: dict[UUID, dict[str, int]] = {}
    component_scores: dict[UUID, dict[str, float]] = {}
    for system_name, ranking in rankings.items():
        seen: set[UUID] = set()
        for rank, result in enumerate(ranking, start=1):
            if result.chunk_id in seen:
                continue
            seen.add(result.chunk_id)
            metadata.setdefault(result.chunk_id, result)
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (
                rrf_constant + rank
            )
            component_ranks.setdefault(result.chunk_id, {})[system_name] = rank
            component_scores.setdefault(result.chunk_id, {})[system_name] = (
                result.similarity_score
            )

    ordered = sorted(
        scores,
        key=lambda chunk_id: (
            -scores[chunk_id],
            min(component_ranks[chunk_id].values()),
            str(chunk_id),
        ),
    )
    if top_k is not None:
        ordered = ordered[:top_k]
    fused: list[FusedRankedChunk] = []
    for chunk_id in ordered:
        original = metadata[chunk_id]
        score = scores[chunk_id]
        fused.append(
            FusedRankedChunk(
                result=VectorSearchResult(
                    chunk_id=original.chunk_id,
                    user_id=original.user_id,
                    document_id=original.document_id,
                    filename=original.filename,
                    page_numbers=original.page_numbers,
                    chunk_text=original.chunk_text,
                    similarity_score=score,
                    section=original.section,
                ),
                rrf_score=score,
                component_ranks=component_ranks[chunk_id],
                component_scores=component_scores[chunk_id],
            )
        )
    return fused
