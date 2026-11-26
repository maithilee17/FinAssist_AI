"""Phase 6 labelled evaluation artifacts remain internally consistent."""

import json
from pathlib import Path


def test_evidence_dataset_and_actual_results_are_complete() -> None:
    root = Path(__file__).parents[1] / "app" / "evaluation"
    dataset = json.loads((root / "evidence_dataset.json").read_text(encoding="utf-8"))
    results = json.loads((root / "evidence_results.json").read_text(encoding="utf-8"))
    assert len(dataset["cases"]) == results["case_count"] == 8
    assert {case["id"] for case in dataset["cases"]} == {
        f"e{index:02d}" for index in range(1, 9)
    }
    assert set(results["experiments"]) == {
        "baseline",
        "evidence_check",
        "claim_verification",
    }
    assert results["experiments"]["claim_verification"]["unsupported_claim_rate"] == 0
    assert (
        results["experiments"]["claim_verification"]["llm_cost_per_query_usd"] is None
    )
