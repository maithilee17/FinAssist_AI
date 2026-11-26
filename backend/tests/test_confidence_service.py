"""Evidence confidence is explainable and never represented as calibrated truth."""

from uuid import uuid4

from app.services.claim_verifier import ClaimVerifier
from app.services.confidence_service import ConfidenceService
from app.services.evidence_verifier import EvidenceVerifier
from app.services.vector_store import VectorSearchResult


def source(text):
    user_id, document_id = uuid4(), uuid4()
    return (
        user_id,
        document_id,
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="report.pdf",
            page_numbers=[4],
            chunk_text=text,
            similarity_score=0.9,
        ),
    )


def test_supported_answer_has_high_explainable_confidence() -> None:
    user_id, document_id, item = source("FY2025 revenue was $1.25 billion.")
    evidence = EvidenceVerifier().verify(
        "What was FY2025 revenue?",
        [item],
        user_id=user_id,
        allowed_document_ids={document_id},
    )
    claims = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion [Source 1].", [item]
    )
    confidence = ConfidenceService().assess(evidence, claims)
    assert confidence.level == "high"
    assert confidence.calibrated_probability is False
    assert confidence.factors["claim_support"] == 1


def test_abstention_evidence_has_low_confidence() -> None:
    user_id, document_id, item = source("The board appointed a new director.")
    evidence = EvidenceVerifier().verify(
        "What was FY2025 revenue?",
        [item],
        user_id=user_id,
        allowed_document_ids={document_id},
    )
    confidence = ConfidenceService().assess(evidence, None)
    assert confidence.level == "low"
    assert confidence.factors["claim_support"] == 0


def test_unsupported_claim_is_policy_capped_to_low_confidence() -> None:
    user_id, document_id, item = source("FY2025 revenue was $1.25 billion.")
    evidence = EvidenceVerifier().verify(
        "What was FY2025 revenue?",
        [item],
        user_id=user_id,
        allowed_document_ids={document_id},
    )
    claims = ClaimVerifier().verify(
        "FY2025 revenue was $9.50 billion [Source 1].", [item]
    )
    confidence = ConfidenceService().assess(evidence, claims)
    assert confidence.level == "low"
    assert confidence.score <= 0.39
