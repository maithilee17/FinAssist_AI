"""Compare baseline, evidence-gated, and claim-verified Phase 6 policies."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import UUID

from app.services.claim_verifier import ClaimStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.vector_store import VectorSearchResult

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "evidence_dataset.json"
RESULTS_PATH = ROOT / "evidence_results.json"
REPORT_PATH = ROOT / "evidence_report.md"
USER_ID = UUID("40000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("50000000-0000-0000-0000-000000000001")


def _passages(values: list[dict[str, object]]) -> list[VectorSearchResult]:
    return [
        VectorSearchResult(
            chunk_id=UUID(str(value["chunk_id"])),
            user_id=USER_ID,
            document_id=DOCUMENT_ID,
            filename="evaluation-report.pdf",
            page_numbers=[int(value["page"])],
            chunk_text=str(value["text"]),
            similarity_score=0.9,
        )
        for value in values
    ]


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _classification(predicted: list[bool], actual: list[bool]) -> dict[str, float]:
    true_positive = sum(p and a for p, a in zip(predicted, actual, strict=True))
    false_positive = sum(p and not a for p, a in zip(predicted, actual, strict=True))
    false_negative = sum(not p and a for p, a in zip(predicted, actual, strict=True))
    return {
        "precision": round(_safe_div(true_positive, true_positive + false_positive), 6),
        "recall": round(_safe_div(true_positive, true_positive + false_negative), 6),
    }


def run() -> dict[str, object]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    evidence_verifier = EvidenceVerifier()
    claim_verifier = ClaimVerifier()
    experiments: dict[str, object] = {}

    for experiment in ("baseline", "evidence_check", "claim_verification"):
        records = []
        evidence_predictions: list[bool] = []
        evidence_actual: list[bool] = []
        abstention_predictions: list[bool] = []
        abstention_actual: list[bool] = []
        claim_predictions: list[bool] = []
        claim_actual: list[bool] = []
        returned_claim_ground_truth: list[bool] = []
        returned_citation_ground_truth: list[bool] = []
        verification_latencies = []
        retrieval_latencies = []
        additional_retrievals = 0
        correct_answers = 0

        for case in dataset["cases"]:
            retrieval_started = perf_counter()
            initial = _passages(case["initial_evidence"])
            evidence = initial
            retrieval_latency = (perf_counter() - retrieval_started) * 1000
            verification_latency = 0.0
            if experiment == "baseline":
                evidence_sufficient = bool(evidence)
            else:
                verify_started = perf_counter()
                assessment = evidence_verifier.verify(
                    case["question"],
                    evidence,
                    user_id=USER_ID,
                    allowed_document_ids={DOCUMENT_ID},
                )
                if assessment.evidence_status == EvidenceStatus.WEAK:
                    additional_retrievals += 1
                    retrieval_started = perf_counter()
                    evidence = list(
                        {
                            item.chunk_id: item
                            for item in evidence + _passages(case["expanded_evidence"])
                        }.values()
                    )
                    retrieval_latency += (perf_counter() - retrieval_started) * 1000
                    assessment = evidence_verifier.verify(
                        case["question"],
                        evidence,
                        user_id=USER_ID,
                        allowed_document_ids={DOCUMENT_ID},
                    )
                evidence_sufficient = (
                    assessment.evidence_status == EvidenceStatus.SUFFICIENT
                )
                verification_latency += (perf_counter() - verify_started) * 1000

            abstained = not evidence_sufficient
            labels = case["claim_labels"]
            predictions: list[bool]
            if evidence_sufficient and experiment == "claim_verification":
                verify_started = perf_counter()
                claim_result = claim_verifier.verify(case["candidate_answer"], evidence)
                verification_latency += (perf_counter() - verify_started) * 1000
                predictions = [
                    claim.status == ClaimStatus.SUPPORTED
                    for claim in claim_result.claims
                ]
                abstained = not any(predictions)
            elif evidence_sufficient:
                predictions = [True] * len(labels)
            else:
                predictions = [False] * len(labels)

            actual_claims = [bool(label["supported"]) for label in labels]
            evidence_predictions.append(evidence_sufficient)
            evidence_actual.append(bool(case["expected_answerable"]))
            abstention_predictions.append(abstained)
            abstention_actual.append(not bool(case["expected_answerable"]))
            if case["expected_answerable"]:
                claim_predictions.extend(predictions)
                claim_actual.extend(actual_claims)
            for predicted, label in zip(predictions, labels, strict=True):
                if predicted:
                    returned_claim_ground_truth.append(bool(label["supported"]))
                    returned_citation_ground_truth.append(
                        bool(label["citation_correct"])
                    )

            if case["expected_answerable"]:
                accepted = [
                    label
                    for predicted, label in zip(predictions, labels, strict=True)
                    if predicted
                ]
                answer_correct = bool(accepted) and all(
                    label["supported"] and label["citation_correct"]
                    for label in accepted
                )
            else:
                answer_correct = abstained
            correct_answers += int(answer_correct)
            verification_latencies.append(verification_latency)
            retrieval_latencies.append(retrieval_latency)
            records.append(
                {
                    "case_id": case["id"],
                    "evidence_sufficient": evidence_sufficient,
                    "abstained": abstained,
                    "claim_support_predictions": predictions,
                    "verification_latency_ms": round(verification_latency, 6),
                }
            )

        evidence_metrics = _classification(evidence_predictions, evidence_actual)
        claim_metrics = _classification(claim_predictions, claim_actual)
        abstention_metrics = _classification(abstention_predictions, abstention_actual)
        experiments[experiment] = {
            "evidence_sufficiency_precision": evidence_metrics["precision"],
            "evidence_sufficiency_recall": evidence_metrics["recall"],
            "claim_support_precision": claim_metrics["precision"],
            "claim_support_recall": claim_metrics["recall"],
            "unsupported_claim_rate": round(
                1 - mean(returned_claim_ground_truth)
                if returned_claim_ground_truth
                else 0.0,
                6,
            ),
            "abstention_precision": abstention_metrics["precision"],
            "abstention_recall": abstention_metrics["recall"],
            "citation_correctness": round(
                mean(returned_citation_ground_truth)
                if returned_citation_ground_truth
                else 0.0,
                6,
            ),
            "answer_correctness": round(correct_answers / len(dataset["cases"]), 6),
            "additional_retrieval_frequency": round(
                additional_retrievals / len(dataset["cases"]), 6
            ),
            "average_retrieval_latency_ms": round(mean(retrieval_latencies), 6),
            "average_verification_latency_ms": round(mean(verification_latencies), 6),
            "llm_cost_per_query_usd": None,
            "records": records,
        }

    results = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": dataset["name"],
        "case_count": len(dataset["cases"]),
        "notes": {
            "llm_cost": "Not measured: candidate answers are versioned fixtures and no provider is called.",
            "latency": "Retrieval latency is fixture materialization; Phase 5 report measures real BGE retrieval.",
        },
        "experiments": experiments,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_report(results), encoding="utf-8")
    return results


def _report(results: dict[str, object]) -> str:
    lines = [
        "# Phase 6 Evidence and Claim Verification Evaluation",
        "",
        f"Generated: {results['generated_at']}",
        "",
        "Eight versioned synthetic cases compare the Phase 5-style ungated baseline, evidence gating, and evidence plus claim verification.",
        "",
        "| Experiment | Evidence P/R | Claim P/R | Unsupported claims | Abstention P/R | Citation correctness | Answer correctness | Extra retrieval | Verify latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "baseline": "A — No verification",
        "evidence_check": "B — Evidence check",
        "claim_verification": "C — Evidence + claims",
    }
    for key, label in labels.items():
        value = results["experiments"][key]
        lines.append(
            f"| {label} | {value['evidence_sufficiency_precision']:.3f}/{value['evidence_sufficiency_recall']:.3f} | "
            f"{value['claim_support_precision']:.3f}/{value['claim_support_recall']:.3f} | "
            f"{value['unsupported_claim_rate']:.3f} | {value['abstention_precision']:.3f}/{value['abstention_recall']:.3f} | "
            f"{value['citation_correctness']:.3f} | {value['answer_correctness']:.3f} | "
            f"{value['additional_retrieval_frequency']:.3f} | {value['average_verification_latency_ms']:.3f} ms |"
        )
    lines.extend(
        [
            "",
            "Candidate answers are fixed fixtures, so no LLM provider was called and cost is reported as unavailable. These small synthetic results validate behavior; they do not establish calibrated real-world accuracy.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(json.dumps(run()["experiments"], indent=2))
