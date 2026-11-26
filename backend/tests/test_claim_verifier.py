"""Independent material-claim and citation verification tests."""

from uuid import uuid4

from app.services.claim_verifier import (
    ClaimOverallStatus,
    ClaimStatus,
    ClaimVerifier,
)
from app.services.vector_store import VectorSearchResult


def evidence(text, page=1):
    return VectorSearchResult(
        chunk_id=uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        filename="annual-report.pdf",
        page_numbers=[page],
        chunk_text=text,
        similarity_score=0.9,
    )


def test_fully_supported_claim_uses_actual_chunk() -> None:
    source = evidence("FY2025 revenue was $1.25 billion.")
    result = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion [Source 1].", [source]
    )
    assert result.overall_status == ClaimOverallStatus.VERIFIED
    assert result.claims[0].status == ClaimStatus.SUPPORTED
    assert result.claims[0].source_chunk_ids == [source.chunk_id]


def test_partially_supported_answer_checks_each_claim() -> None:
    source = evidence("FY2025 revenue was $1.25 billion.")
    result = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion [Source 1]. Net profit fell by 4% [Source 1].",
        [source],
    )
    assert result.overall_status == ClaimOverallStatus.PARTIALLY_SUPPORTED
    assert result.supported_claims == 1
    assert result.unsupported_claims + result.partially_supported_claims == 1


def test_unsupported_number_and_incorrect_period_are_not_verified() -> None:
    source = evidence("FY2025 revenue was $1.25 billion.")
    wrong_value = ClaimVerifier().verify(
        "FY2025 revenue was $9.50 billion [Source 1].", [source]
    )
    wrong_period = ClaimVerifier().verify(
        "FY2024 revenue was $1.25 billion [Source 1].", [source]
    )
    assert wrong_value.overall_status != ClaimOverallStatus.VERIFIED
    assert wrong_period.overall_status != ClaimOverallStatus.VERIFIED


def test_wrong_or_out_of_range_citation_is_invalid() -> None:
    correct = evidence("FY2025 revenue was $1.25 billion.")
    unrelated = evidence("The board declared a dividend.", page=8)
    wrong_source = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion [Source 2].", [correct, unrelated]
    )
    invalid_source = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion [Source 9].", [correct, unrelated]
    )
    assert wrong_source.claims[0].status != ClaimStatus.SUPPORTED
    assert invalid_source.claims[0].citation_valid is False


def test_material_claim_without_source_reference_is_not_verified() -> None:
    source = evidence("FY2025 revenue was $1.25 billion.")
    result = ClaimVerifier().verify("FY2025 revenue was $1.25 billion.", [source])
    assert result.overall_status == ClaimOverallStatus.UNSUPPORTED
    assert result.claims[0].citation_valid is False


def test_multiple_claims_can_resolve_to_different_sources() -> None:
    revenue = evidence("FY2025 revenue was $1.25 billion.")
    profit = evidence("FY2025 net profit was $146 million.", page=2)
    result = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion [Source 1]. FY2025 net profit was $146 million [Source 2].",
        [revenue, profit],
    )
    assert result.overall_status == ClaimOverallStatus.VERIFIED
    assert {
        result.claims[0].source_chunk_ids[0],
        result.claims[1].source_chunk_ids[0],
    } == {
        revenue.chunk_id,
        profit.chunk_id,
    }


def test_citation_after_sentence_punctuation_attaches_to_claim() -> None:
    source = evidence("FY2025 revenue was $1.25 billion.")
    result = ClaimVerifier().verify(
        "FY2025 revenue was $1.25 billion. [Source 1]", [source]
    )
    assert result.overall_status == ClaimOverallStatus.VERIFIED
    assert result.claims_checked == 1
