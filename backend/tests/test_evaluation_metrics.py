"""Known-answer tests for retrieval evaluation metrics and dataset labels."""

import json
from pathlib import Path

import pytest

from app.evaluation.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_metrics_use_binary_chunk_relevance() -> None:
    ranking = ["irrelevant", "a", "b"]
    relevant = {"a", "b"}
    assert precision_at_k(ranking, relevant, 3) == pytest.approx(2 / 3)
    assert recall_at_k(ranking, relevant, 3) == 1.0
    assert reciprocal_rank(ranking, relevant) == 0.5
    assert 0 < ndcg_at_k(ranking, relevant, 3) < 1


def test_evaluation_dataset_has_unique_chunks_and_all_labels_resolve() -> None:
    path = Path(__file__).parents[1] / "app" / "evaluation" / "dataset.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    chunk_ids = [chunk["chunk_id"] for chunk in dataset["chunks"]]
    assert len(chunk_ids) == len(set(chunk_ids))
    known = set(chunk_ids)
    for question in dataset["questions"]:
        assert set(question["relevant_chunk_ids"]) <= known
        assert question["expected_strategy"] in {"keyword", "semantic", "hybrid"}
