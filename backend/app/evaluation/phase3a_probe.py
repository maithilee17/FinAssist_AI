"""Comparable offline Phase 3A probes; NOT live retrieval/Ollama measurements."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from uuid import UUID

from app.services.adaptive_retrieval import AdaptiveRetrievalSelector
from app.services.financial_calculation import calculate
from app.services.query_analyzer import FinancialQueryAnalyzer
from app.services.vector_store import VectorSearchResult

PRODUCTS = "What products did Northstar Components manufacture in FY2024 and what was its sales model?"
CASH = "Summarize the cash flows for Riverton Industries in FY2025 including operating, investing, and financing activities and net change in cash."
TEXT = """Riverton Industries FY2025
Net cash from operating activities
$135,000
Net cash used in investing activities
($90,000)
Net cash used in financing activities
($25,000)
Cash at beginning of year
$60,000
Cash at end of year
$80,000
Net increase in cash
$20,000"""


def probe(repetitions=100):
    rows = [
        VectorSearchResult(
            chunk_id=UUID(int=1),
            user_id=UUID(int=2),
            document_id=UUID(int=3),
            filename="offline-fixture.pdf",
            page_numbers=[2],
            chunk_text=TEXT,
            similarity_score=0.8,
        )
    ]
    analyzer, selector = FinancialQueryAnalyzer(), AdaptiveRetrievalSelector()
    routing, arithmetic = [], []
    for _ in range(repetitions + 10):
        start = perf_counter()
        route = selector.select(analyzer.analyze(PRODUCTS))
        routing.append((perf_counter() - start) * 1000)
        start = perf_counter()
        result = calculate(CASH, rows)
        try:
            from app.services.financial_calculation import cash_flow_summary
        except ImportError:
            summary = None
        else:
            summary = cash_flow_summary(CASH, rows)
        arithmetic.append((perf_counter() - start) * 1000)

    def timing(values):
        values = values[10:]
        return {
            "mean_ms": mean(values),
            "median_ms": median(values),
            "p95_ms": sorted(values)[int(len(values) * 0.95) - 1],
        }

    root = Path(__file__).parents[2]
    files = [
        "query_analyzer.py",
        "financial_calculation.py",
        "rag_pipeline.py",
        "evidence_verifier.py",
        "claim_verifier.py",
    ]
    return {
        "scope": "offline fixed text; no BM25/Chroma/BGE/Ollama latency or live accuracy",
        "repetitions": repetitions,
        "warmup_iterations": 10,
        "products_question": PRODUCTS,
        "products_analysis": asdict(analyzer.analyze(PRODUCTS)),
        "products_strategy": route.selected_strategy.value,
        "cash_question": CASH,
        "calculator_answer": result.answer if result else None,
        "summary_answer": summary.answer if summary else None,
        "routing": timing(routing),
        "calculation_and_summary": timing(arithmetic),
        "source_sha256": {
            name: hashlib.sha256(
                (root / "app/services" / name).read_bytes()
            ).hexdigest()
            for name in files
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(probe(), target, indent=2, default=str)
