"""Standard information-retrieval metrics for labelled chunk rankings."""

from __future__ import annotations

from math import log2


def precision_at_k(ranking: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranking[:k]) & relevant) / k if k > 0 else 0.0


def recall_at_k(ranking: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranking[:k]) & relevant) / len(relevant) if relevant else 0.0


def reciprocal_rank(ranking: list[str], relevant: set[str]) -> float:
    for rank, chunk_id in enumerate(ranking, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranking: list[str], relevant: set[str], k: int) -> float:
    gains = [1.0 if chunk_id in relevant else 0.0 for chunk_id in ranking[:k]]
    dcg = sum(gain / log2(index + 2) for index, gain in enumerate(gains))
    ideal_hits = min(len(relevant), k)
    ideal = sum(1.0 / log2(index + 2) for index in range(ideal_hits))
    return dcg / ideal if ideal else 0.0
