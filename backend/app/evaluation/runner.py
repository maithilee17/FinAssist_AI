"""Run semantic, always-hybrid, and adaptive retrieval on one labelled corpus."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import UUID

from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.evaluation.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalSelector,
    RetrievalStrategy,
)
from app.services.embedding_service import EmbeddingService
from app.services.keyword_retrieval import tokenize_financial_text
from app.services.query_analyzer import FinancialQueryAnalyzer
from app.services.rank_fusion import reciprocal_rank_fusion
from app.services.vector_store import VectorSearchResult

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "dataset.json"
RESULTS_PATH = ROOT / "results.json"
REPORT_PATH = ROOT / "report.md"
EVALUATION_USER_ID = UUID("20000000-0000-0000-0000-000000000001")


def _vector_result(chunk: dict[str, object], score: float) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=UUID(str(chunk["chunk_id"])),
        user_id=EVALUATION_USER_ID,
        document_id=UUID(str(chunk["document_id"])),
        filename=str(chunk["filename"]),
        page_numbers=list(chunk["page_numbers"]),
        chunk_text=str(chunk["text"]),
        similarity_score=score,
    )


def _aggregate(records: list[dict[str, object]]) -> dict[str, float]:
    metric_names = ("precision_at_k", "recall_at_k", "mrr", "ndcg_at_k", "latency_ms")
    return {
        metric: round(mean(float(record[metric]) for record in records), 6)
        for metric in metric_names
    }


def _render_report(results: dict[str, object]) -> str:
    lines = [
        "# Phase 5 Retrieval Evaluation",
        "",
        f"Generated: {results['generated_at']}",
        "",
        (
            "This is an actual offline retrieval run over the versioned synthetic benchmark. "
            "It uses the configured BGE model and the production BM25 tokenizer/RRF rules; it "
            "does not call the LLM or claim answer-quality results."
        ),
        "",
        f"- Dataset: `{results['dataset']['name']}`",
        f"- Questions: {results['dataset']['question_count']}",
        f"- Chunks: {results['dataset']['chunk_count']}",
        f"- top_k: {results['dataset']['top_k']}",
        f"- Embedding model: `{results['embedding_model']}`",
        "",
        "| Configuration | Precision@K | Recall@K | MRR | nDCG@K | Avg latency (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "semantic_only": "A — Semantic only",
        "hybrid_all": "B — Hybrid for all",
        "adaptive": "C — Adaptive",
    }
    for key, label in labels.items():
        aggregate = results["experiments"][key]["aggregate"]
        lines.append(
            f"| {label} | {aggregate['precision_at_k']:.4f} | "
            f"{aggregate['recall_at_k']:.4f} | {aggregate['mrr']:.4f} | "
            f"{aggregate['ndcg_at_k']:.4f} | {aggregate['latency_ms']:.3f} |"
        )
    accuracy = results["experiments"]["adaptive"]["strategy_selection_accuracy"]
    lines.extend(
        [
            "",
            f"Adaptive strategy-selection accuracy: **{accuracy:.2%}**.",
            "",
            (
                "The corpus is intentionally small and synthetic, so these measurements validate "
                "the evaluation path rather than establish statistically general performance. "
                "Latency excludes one-time model loading and document embedding/index construction."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, object]:
    raw_dataset = DATASET_PATH.read_bytes()
    dataset = json.loads(raw_dataset)
    chunks: list[dict[str, object]] = dataset["chunks"]
    questions: list[dict[str, object]] = dataset["questions"]
    top_k = int(dataset["top_k"])
    settings = get_settings()
    embedding = EmbeddingService(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
        query_prefix=settings.embedding_query_prefix,
    )
    document_embeddings = embedding.embed_documents(
        [str(chunk["text"]) for chunk in chunks]
    )
    tokenized_corpus = [tokenize_financial_text(str(chunk["text"])) for chunk in chunks]
    bm25 = BM25Okapi(
        tokenized_corpus,
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        epsilon=settings.bm25_epsilon,
    )
    analyzer = FinancialQueryAnalyzer()
    selector = AdaptiveRetrievalSelector(
        exact_term_threshold=settings.adaptive_exact_term_threshold
    )

    def semantic(question: str) -> list[VectorSearchResult]:
        query_embedding = embedding.embed_query(question)
        scored = [
            _vector_result(
                chunk, sum(a * b for a, b in zip(query_embedding, vector, strict=True))
            )
            for chunk, vector in zip(chunks, document_embeddings, strict=True)
        ]
        return sorted(
            scored, key=lambda item: (-item.similarity_score, str(item.chunk_id))
        )[:top_k]

    def keyword(question: str) -> list[VectorSearchResult]:
        query_tokens = tokenize_financial_text(question)
        scores = bm25.get_scores(query_tokens)
        query_set = set(query_tokens)
        scored = [
            _vector_result(chunk, float(score))
            for chunk, tokens, score in zip(
                chunks, tokenized_corpus, scores, strict=True
            )
            if query_set.intersection(tokens)
        ]
        return sorted(
            scored, key=lambda item: (-item.similarity_score, str(item.chunk_id))
        )[:top_k]

    def hybrid(question: str) -> list[VectorSearchResult]:
        fused = reciprocal_rank_fusion(
            {"keyword": keyword(question), "semantic": semantic(question)},
            rrf_constant=settings.rrf_constant,
            top_k=top_k,
        )
        return [item.result for item in fused]

    experiments: dict[str, dict[str, object]] = {}
    configurations = {
        "semantic_only": lambda question: (
            RetrievalStrategy.SEMANTIC,
            semantic(question),
        ),
        "hybrid_all": lambda question: (RetrievalStrategy.HYBRID, hybrid(question)),
    }

    def adaptive(question: str) -> tuple[RetrievalStrategy, list[VectorSearchResult]]:
        strategy = selector.select(analyzer.analyze(question)).selected_strategy
        retriever = {
            RetrievalStrategy.KEYWORD: keyword,
            RetrievalStrategy.SEMANTIC: semantic,
            RetrievalStrategy.HYBRID: hybrid,
        }[strategy]
        return strategy, retriever(question)

    configurations["adaptive"] = adaptive
    for experiment_name, retrieve in configurations.items():
        records: list[dict[str, object]] = []
        correct_routes = 0
        for item in questions:
            started = perf_counter()
            strategy, ranking = retrieve(str(item["question"]))
            latency_ms = (perf_counter() - started) * 1000
            ranked_ids = [str(result.chunk_id) for result in ranking]
            relevant = set(item["relevant_chunk_ids"])
            expected = str(item["expected_strategy"])
            if strategy.value == expected:
                correct_routes += 1
            records.append(
                {
                    "question_id": item["id"],
                    "question": item["question"],
                    "expected_strategy": expected,
                    "selected_strategy": strategy.value,
                    "ranked_chunk_ids": ranked_ids,
                    "precision_at_k": precision_at_k(ranked_ids, relevant, top_k),
                    "recall_at_k": recall_at_k(ranked_ids, relevant, top_k),
                    "mrr": reciprocal_rank(ranked_ids, relevant),
                    "ndcg_at_k": ndcg_at_k(ranked_ids, relevant, top_k),
                    "latency_ms": round(latency_ms, 6),
                }
            )
        experiment: dict[str, object] = {
            "aggregate": _aggregate(records),
            "queries": records,
        }
        if experiment_name == "adaptive":
            experiment["strategy_selection_accuracy"] = correct_routes / len(questions)
        experiments[experiment_name] = experiment

    results: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "embedding_model": settings.embedding_model,
        "dataset": {
            "name": dataset["name"],
            "sha256": hashlib.sha256(raw_dataset).hexdigest(),
            "chunk_count": len(chunks),
            "question_count": len(questions),
            "top_k": top_k,
        },
        "configuration": {
            "bm25": {
                "k1": settings.bm25_k1,
                "b": settings.bm25_b,
                "epsilon": settings.bm25_epsilon,
            },
            "rrf_constant": settings.rrf_constant,
            "query_prefix": settings.embedding_query_prefix,
        },
        "experiments": experiments,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(results), encoding="utf-8")
    return results


if __name__ == "__main__":
    print(json.dumps(run()["experiments"], indent=2))
