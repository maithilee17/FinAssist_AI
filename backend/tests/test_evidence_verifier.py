"""Evidence relevance, requirement coverage, and sufficiency decisions."""

from uuid import uuid4

from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.vector_store import VectorSearchResult


def passage(text, *, user_id, document_id, page=1, filename="report.pdf"):
    return VectorSearchResult(
        chunk_id=uuid4(),
        user_id=user_id,
        document_id=document_id,
        filename=filename,
        page_numbers=[page],
        chunk_text=text,
        similarity_score=0.9,
    )


def verify(question, passages, user_id, document_id):
    return EvidenceVerifier().verify(
        question,
        passages,
        user_id=user_id,
        allowed_document_ids={document_id},
    )


def test_exact_figure_and_period_are_sufficient() -> None:
    user_id, document_id = uuid4(), uuid4()
    result = verify(
        "What was net profit in FY2025?",
        [
            passage(
                "FY2025 net profit was $146 million.",
                user_id=user_id,
                document_id=document_id,
            )
        ],
        user_id,
        document_id,
    )
    assert result.evidence_status == EvidenceStatus.SUFFICIENT
    assert result.missing_aspects == []
    assert "2025 profit" in result.supported_aspects


def test_comparison_with_one_period_is_weak() -> None:
    user_id, document_id = uuid4(), uuid4()
    result = verify(
        "Compare revenue in FY2024 and FY2025.",
        [
            passage(
                "FY2025 revenue was $1.25 billion.",
                user_id=user_id,
                document_id=document_id,
            )
        ],
        user_id,
        document_id,
    )
    assert result.evidence_status == EvidenceStatus.WEAK
    assert "2024 revenue" in result.missing_aspects
    assert "2025 revenue" in result.supported_aspects


def test_unrelated_passage_is_insufficient() -> None:
    user_id, document_id = uuid4(), uuid4()
    result = verify(
        "What was FY2025 net profit?",
        [
            passage(
                "The board appointed a new chairperson.",
                user_id=user_id,
                document_id=document_id,
            )
        ],
        user_id,
        document_id,
    )
    assert result.evidence_status == EvidenceStatus.INSUFFICIENT
    assert result.relevance_score == 0
    assert "2025 profit" in result.missing_aspects


def test_multiple_passages_can_jointly_satisfy_comparison() -> None:
    user_id, document_id = uuid4(), uuid4()
    result = verify(
        "Compare revenue in FY2024 and FY2025.",
        [
            passage(
                "FY2024 revenue was $1.10 billion.",
                user_id=user_id,
                document_id=document_id,
            ),
            passage(
                "FY2025 revenue was $1.25 billion.",
                user_id=user_id,
                document_id=document_id,
                page=2,
            ),
        ],
        user_id,
        document_id,
    )
    assert result.evidence_status == EvidenceStatus.SUFFICIENT
    assert result.source_validity_score == 1


def test_invalid_ownership_or_page_metadata_cannot_be_sufficient() -> None:
    user_id, document_id = uuid4(), uuid4()
    wrong_owner = passage(
        "FY2025 revenue was $1.25 billion.", user_id=uuid4(), document_id=document_id
    )
    result = verify("What was FY2025 revenue?", [wrong_owner], user_id, document_id)
    assert result.evidence_status == EvidenceStatus.INSUFFICIENT
    assert result.source_validity_score == 0


def test_company_and_comparison_units_must_match() -> None:
    user_id, document_id = uuid4(), uuid4()
    result = verify(
        "Compare Acme Corp revenue in FY2024 and FY2025.",
        [
            passage(
                "Acme Corp FY2024 revenue was $1.10 billion.",
                user_id=user_id,
                document_id=document_id,
            ),
            passage(
                "Acme Corp FY2025 revenue was €1.25 billion.",
                user_id=user_id,
                document_id=document_id,
                page=2,
            ),
        ],
        user_id,
        document_id,
    )
    assert result.evidence_status == EvidenceStatus.WEAK
    assert "consistent currency or units" in result.missing_aspects


def test_metric_period_must_be_supported_in_same_local_passage() -> None:
    user_id, document_id = uuid4(), uuid4()
    result = verify(
        "What was revenue in FY2030?",
        [
            passage(
                "Revenue was $10 million in 2025. "
                + ("unrelated disclosure " * 80)
                + "A lease expires in 2030.",
                user_id=user_id,
                document_id=document_id,
            )
        ],
        user_id,
        document_id,
    )
    assert result.evidence_status != EvidenceStatus.SUFFICIENT
    assert "2030 revenue" in result.missing_aspects


def test_unreported_ratio_and_ambiguous_profit_are_not_sufficient() -> None:
    user_id, document_id = uuid4(), uuid4()
    source = passage(
        "In 2025 debt was $20 million and total equity was $40 million. Net income was $8 million.",
        user_id=user_id,
        document_id=document_id,
    )
    ratio = verify(
        "What debt-to-equity ratio was reported in 2025?",
        [source],
        user_id,
        document_id,
    )
    ambiguous = verify("What was profit in 2025?", [source], user_id, document_id)
    assert ratio.evidence_status != EvidenceStatus.SUFFICIENT
    assert "explicit requested ratio" in ratio.missing_aspects
    assert ambiguous.evidence_status == EvidenceStatus.WEAK
    assert any("clarification needed" in value for value in ambiguous.missing_aspects)
