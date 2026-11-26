from dataclasses import replace
from uuid import uuid4

import pytest

from app.services.adaptive_retrieval import AdaptiveRetrievalSelector, RetrievalStrategy
from app.services.claim_verifier import ClaimOverallStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import calculate
from app.services.query_analyzer import FinancialQueryAnalyzer
from app.services.vector_store import VectorSearchResult


def passages(text):
    return [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=uuid4(),
            document_id=uuid4(),
            filename="sample.pdf",
            page_numbers=[1],
            chunk_text=text,
            similarity_score=0.8,
        )
    ]


@pytest.mark.parametrize(
    "question,text,value",
    [
        (
            "Calculate its gross profit margin.",
            "Revenue: $850,000\nCOGS: $510,000",
            "40.00%",
        ),
        (
            "Calculate gross margin.",
            "Revenue: $850,000\nGross profit: $340,000",
            "40.00%",
        ),
        (
            "What percentage of revenue remains after COGS?",
            "Revenue: $850,000\nCOGS: $510,000",
            "40.00%",
        ),
        (
            "Find the gross profit margin using the figures in the report.",
            "Revenue: $850,000\nGross profit: $340,000",
            "40.00%",
        ),
        (
            "What is gross profit divided by revenue?",
            "Revenue: $850,000\nGross profit: $340,000",
            "40.00%",
        ),
        (
            "Calculate net profit margin.",
            "Revenue: $850,000\nNet profit: $96,000",
            "11.29%",
        ),
        (
            "Calculate debt-to-assets ratio.",
            "Total liabilities: $360,000\nTotal assets: $600,000",
            "60.00%",
        ),
        (
            "Calculate current ratio.",
            "Current assets: $300,000\nCurrent liabilities: $160,000",
            "1.875x",
        ),
        (
            "Calculate operating margin.",
            "Operating profit: $170,000\nRevenue: $850,000",
            "20.00%",
        ),
        (
            "Calculate gross profit.",
            "Revenue: $850,000\nCOGS: $510,000",
            "340000.00 USD",
        ),
        (
            "Calculate working capital.",
            "Current assets: $300,000\nCurrent liabilities: $160,000",
            "140000.00 USD",
        ),
    ],
)
def test_verified_financial_calculations(question, text, value):
    evidence = passages(text)
    result = calculate(question, evidence)
    assert result and value in result.answer
    assert "[Source 1]" in result.answer and "Derived" in result.answer
    assert (
        EvidenceVerifier()
        .verify(
            question,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        .evidence_status
        == EvidenceStatus.SUFFICIENT
    )
    verified = ClaimVerifier().verify(result.answer, evidence)
    assert verified.overall_status == ClaimOverallStatus.VERIFIED
    assert verified.claims[0].source_chunk_ids == [evidence[0].chunk_id]
    assert (
        ClaimVerifier()
        .verify(result.answer.replace(value, "999999%"), evidence)
        .overall_status
        != ClaimOverallStatus.VERIFIED
    )


@pytest.mark.parametrize(
    "text",
    [
        "Revenue: $850,000",
        "Revenue: $0\nGross profit: $340,000",
        "Revenue: $850,000\nGross profit: EUR 340,000",
        "Revenue: $850,000\nRevenue: $700,000\nGross profit: $340,000",
        "FY2024 FY2025\nRevenue: $850,000\nGross profit: $340,000",
    ],
)
def test_missing_ambiguous_or_invalid_inputs_abstain(text):
    assert calculate("Calculate gross margin", passages(text)) is None


def test_ownership_and_document_isolation():
    evidence = passages("Revenue: $850,000\nGross profit: $340,000")
    for user, docs in [
        (uuid4(), {evidence[0].document_id}),
        (evidence[0].user_id, {uuid4()}),
    ]:
        assert (
            EvidenceVerifier()
            .verify(
                "Calculate gross margin",
                evidence,
                user_id=user,
                allowed_document_ids=docs,
            )
            .evidence_status
            != EvidenceStatus.SUFFICIENT
        )
    assert (
        calculate(
            "Calculate gross margin",
            evidence + [replace(evidence[0], document_id=uuid4())],
        )
        is None
    )


def test_calculation_routes_hybrid_without_changing_exact_facts():
    analyzer = FinancialQueryAnalyzer()
    selector = AdaptiveRetrievalSelector()
    assert (
        selector.select(analyzer.analyze("Calculate gross margin")).selected_strategy
        == RetrievalStrategy.HYBRID
    )
    assert (
        selector.select(
            analyzer.analyze("What was revenue in FY2025?")
        ).selected_strategy
        == RetrievalStrategy.KEYWORD
    )


def test_calculation_keeps_citations_for_inputs_on_separate_pages():
    evidence = passages("Revenue: $850,000")
    evidence.append(
        replace(
            evidence[0], chunk_id=uuid4(), page_numbers=[2], chunk_text="COGS: $510,000"
        )
    )
    proof = calculate("Calculate gross margin", evidence)
    assert proof and "40.00%" in proof.answer
    assert "[Source 1]" in proof.answer and "[Source 2]" in proof.answer
    checked = ClaimVerifier().verify(proof.answer, evidence)
    assert checked.overall_status == ClaimOverallStatus.VERIFIED
    assert set(checked.claims[0].source_chunk_ids) == {x.chunk_id for x in evidence}


def test_percentage_formatting_is_not_a_fact_conflict():
    evidence = passages("Gross profit margin was 40%.")
    assert (
        ClaimVerifier()
        .verify("Gross profit margin was 40.00% [Source 1].", evidence)
        .overall_status
        == ClaimOverallStatus.VERIFIED
    )


def test_empty_keyword_ranking_preserves_semantic_evidence():
    from app.services.rank_fusion import reciprocal_rank_fusion

    evidence = passages("Revenue: $850,000")
    fused = reciprocal_rank_fusion({"keyword": [], "semantic": evidence})
    assert len(fused) == 1
    assert fused[0].result.chunk_id == evidence[0].chunk_id
    assert fused[0].result.document_id == evidence[0].document_id
    assert fused[0].result.user_id == evidence[0].user_id
    assert fused[0].result.page_numbers == evidence[0].page_numbers
