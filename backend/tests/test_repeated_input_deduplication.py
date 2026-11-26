"""Regression tests for repeated-value deduplication and cross-isolation.

Covers the FY2025 gross-profit-margin failure where identical financial figures
appearing in multiple retrieved chunks (executive summary, income statement,
calculation note, ratio table) were incorrectly marked invalid because non-data
label mentions were treated as malformed data rows.
"""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.claim_verifier import ClaimOverallStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import (
    _deduplicate_inputs,
    calculate,
    extract_calculation_inputs,
)
from app.services.vector_store import VectorSearchResult

QUESTION = "Calculate gross profit margin for FY2025."


def _make_evidence(*chunk_texts):
    """Build evidence list sharing one user, document, and filename."""
    user_id = uuid4()
    document_id = uuid4()
    return [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="FinAssist_Sample_Financial_Report.pdf",
            page_numbers=[i + 1],
            chunk_text=text,
            similarity_score=0.85,
        )
        for i, text in enumerate(chunk_texts)
    ]


# ---------------------------------------------------------------------------
# 1) Repeated identical values across executive summary, income statement,
#    and calculation note — should be accepted and correctly cited.
# ---------------------------------------------------------------------------


class TestRepeatedIdenticalValues:
    """Revenue and gross profit appear three times with the same amount."""

    @pytest.fixture()
    def evidence(self):
        return _make_evidence(
            # Chunk 1: title + executive summary
            "Northstar Components FY2025\nRevenue: $850,000\nGross profit: $340,000\n"
            "Net income: $96,000",
            # Chunk 2: income statement
            "Revenue: $850,000\nCOGS: $510,000\nGross profit: $340,000\n"
            "Operating income: $160,000\nNet income: $96,000",
            # Chunk 3: calculation note (descriptive mentions + ratio)
            "Revenue: $850,000\nGross profit: $340,000\n"
            "Gross profit margin: 40.00%\n"
            "Gross profit divided by Revenue",
        )

    def test_extraction_accepts_repeated_identical_revenue(self, evidence):
        facts, invalid = extract_calculation_inputs(evidence)
        assert "revenue" in facts, f"revenue missing; invalid={invalid}"
        assert facts["revenue"].amount == Decimal(850000)
        assert "revenue" not in invalid

    def test_extraction_accepts_repeated_identical_gross_profit(self, evidence):
        facts, invalid = extract_calculation_inputs(evidence)
        assert "gross profit" in facts, f"gross profit missing; invalid={invalid}"
        assert facts["gross profit"].amount == Decimal(340000)
        assert "gross profit" not in invalid

    def test_extraction_accepts_net_income_alias(self, evidence):
        facts, invalid = extract_calculation_inputs(evidence)
        assert "net profit" in facts, f"net profit missing; invalid={invalid}"
        assert facts["net profit"].amount == Decimal(96000)

    def test_extraction_accepts_operating_income_alias(self, evidence):
        facts, _invalid = extract_calculation_inputs(evidence)
        assert "operating profit" in facts
        assert facts["operating profit"].amount == Decimal(160000)

    def test_gross_margin_returns_exactly_40_percent(self, evidence):
        proof = calculate(QUESTION, evidence)
        assert proof is not None, "calculation returned None"
        assert "40.00%" in proof.answer
        assert "FY2025" in proof.answer

    def test_provenance_is_traceable(self, evidence):
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        for fact in proof.inputs:
            source = evidence[fact.source_number - 1]
            assert fact.excerpt == source.chunk_text[fact.start : fact.end]
            assert fact.chunk_id == source.chunk_id
            assert fact.document_id == source.document_id
            assert fact.user_id == source.user_id
            assert fact.filename == source.filename
            assert fact.page_numbers == tuple(source.page_numbers)

    def test_evidence_verification_is_sufficient(self, evidence):
        result = EvidenceVerifier().verify(
            QUESTION,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status == EvidenceStatus.SUFFICIENT

    def test_claim_verification_is_verified(self, evidence):
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        checked = ClaimVerifier().verify(proof.answer, evidence)
        assert checked.overall_status == ClaimOverallStatus.VERIFIED
        assert checked.supported_claims == 1


# ---------------------------------------------------------------------------
# 2) Same values in a ratio table — should not invalidate.
# ---------------------------------------------------------------------------


class TestValuesInRatioTable:
    """Revenue appears as a data row AND in a ratio description."""

    def test_ratio_description_does_not_invalidate_revenue(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
            "Financial Ratios\nGross profit divided by Revenue\n"
            "Gross profit margin: 40.00%",
        )
        facts, invalid = extract_calculation_inputs(evidence)
        assert "revenue" in facts
        assert "revenue" not in invalid

    def test_gross_margin_with_ratio_table_chunk(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
            "Financial Ratios\nGross profit divided by Revenue\n"
            "Gross profit margin: 40.00%",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer


# ---------------------------------------------------------------------------
# 3) Repeated identical values being accepted and correctly cited.
# ---------------------------------------------------------------------------


class TestDeduplication:
    """The _deduplicate_inputs function correctly collapses identical mentions."""

    def test_identical_values_collapse_to_one(self):
        from app.services.financial_calculation import FinancialInput

        doc_id, user_id = uuid4(), uuid4()
        base = FinancialInput(
            "revenue",
            Decimal(850000),
            "USD",
            1,
            uuid4(),
            doc_id,
            user_id,
            "report.pdf",
            (1,),
            0,
            10,
            "Revenue: $850,000",
        )
        second = FinancialInput(
            "revenue",
            Decimal(850000),
            "USD",
            2,
            uuid4(),
            doc_id,
            user_id,
            "report.pdf",
            (2,),
            0,
            10,
            "Revenue: $850,000",
        )
        result = _deduplicate_inputs([base, second])
        assert len(result) == 1
        assert result[0] is base  # first occurrence retained

    def test_different_amounts_kept_separate(self):
        from app.services.financial_calculation import FinancialInput

        doc_id, user_id = uuid4(), uuid4()
        a = FinancialInput(
            "revenue",
            Decimal(850000),
            "USD",
            1,
            uuid4(),
            doc_id,
            user_id,
            "report.pdf",
            (1,),
            0,
            10,
            "Revenue: $850,000",
        )
        b = FinancialInput(
            "revenue",
            Decimal(700000),
            "USD",
            2,
            uuid4(),
            doc_id,
            user_id,
            "report.pdf",
            (2,),
            0,
            10,
            "Revenue: $700,000",
        )
        result = _deduplicate_inputs([a, b])
        assert len(result) == 2

    def test_different_documents_kept_separate(self):
        from app.services.financial_calculation import FinancialInput

        user_id = uuid4()
        a = FinancialInput(
            "revenue",
            Decimal(850000),
            "USD",
            1,
            uuid4(),
            uuid4(),
            user_id,
            "report.pdf",
            (1,),
            0,
            10,
            "Revenue: $850,000",
        )
        b = FinancialInput(
            "revenue",
            Decimal(850000),
            "USD",
            2,
            uuid4(),
            uuid4(),
            user_id,
            "other.pdf",
            (1,),
            0,
            10,
            "Revenue: $850,000",
        )
        result = _deduplicate_inputs([a, b])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 4) Conflicting repeated values cause abstention.
# ---------------------------------------------------------------------------


class TestConflictingValuesAbstain:
    def test_conflicting_revenue_across_chunks(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
            "Revenue: $700,000\nCOGS: $510,000",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is None

    def test_conflicting_cogs_across_chunks(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
            "Revenue: $850,000\nCOGS: $490,000",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is None

    def test_conflicting_gross_profit_across_chunks(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nGross profit: $340,000",
            "Revenue: $850,000\nGross profit: $350,000",
        )
        # Gross profit values conflict
        _facts, invalid = extract_calculation_inputs(evidence)
        assert "gross profit" in invalid

    def test_conflicting_revenue_still_abstains_with_evidence_verifier(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
            "Revenue: $700,000\nCOGS: $510,000",
        )
        result = EvidenceVerifier().verify(
            QUESTION,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status != EvidenceStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# 5) Different reporting years cause abstention.
# ---------------------------------------------------------------------------


class TestPeriodIsolation:
    def test_different_years_in_evidence_abstains(self):
        evidence = _make_evidence(
            "Northstar Components FY2024\nRevenue: $780,000\nCOGS: $468,000",
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is None

    def test_mismatched_requested_year_abstains(self):
        evidence = _make_evidence(
            "Northstar Components FY2024\nRevenue: $850,000\nCOGS: $510,000",
        )
        proof = calculate("Calculate gross profit margin for FY2025.", evidence)
        assert proof is None


# ---------------------------------------------------------------------------
# 6) Different currencies cause abstention.
# ---------------------------------------------------------------------------


class TestCurrencyIsolation:
    def test_mixed_currencies_abstain(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: €510,000",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is None

    def test_cross_chunk_currency_mismatch_abstains(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000",
            "COGS: €510,000",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is None


# ---------------------------------------------------------------------------
# 7) Cross-document and cross-user isolation.
# ---------------------------------------------------------------------------


class TestCrossIsolation:
    def test_cross_document_abstains(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000",
        )
        second_chunk = replace(
            evidence[0],
            chunk_id=uuid4(),
            document_id=uuid4(),  # different document!
            page_numbers=[2],
            chunk_text="COGS: $510,000",
        )
        proof = calculate(QUESTION, evidence + [second_chunk])
        assert proof is None

    def test_cross_user_abstains(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000",
        )
        second_chunk = replace(
            evidence[0],
            chunk_id=uuid4(),
            user_id=uuid4(),  # different user!
            page_numbers=[2],
            chunk_text="COGS: $510,000",
        )
        proof = calculate(QUESTION, evidence + [second_chunk])
        assert proof is None

    def test_evidence_verifier_cross_user_isolation(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
        )
        result = EvidenceVerifier().verify(
            QUESTION,
            evidence,
            user_id=uuid4(),  # wrong user
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status != EvidenceStatus.SUFFICIENT

    def test_evidence_verifier_cross_document_isolation(self):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
        )
        result = EvidenceVerifier().verify(
            QUESTION,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={uuid4()},  # wrong document
        )
        assert result.evidence_status != EvidenceStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# 8) FY2025 gross profit margin returns exactly 40.00%.
# ---------------------------------------------------------------------------


class TestFY2025ExactResult:
    """Reproduce the exact live failure scenario from the diagnostic trace."""

    def test_three_chunk_scenario_returns_40_percent(self):
        """Three chunks with the PDF content described in the trace."""
        evidence = _make_evidence(
            # Chunk 1: executive summary + period context
            "Northstar Components\nFY2025 financial report\n"
            "Revenue: $850,000\nGross profit: $340,000\nNet income: $96,000",
            # Chunk 2: income statement
            "Revenue: $850,000\nCOGS: $510,000\nGross profit: $340,000\n"
            "Operating income: $160,000\nNet income: $96,000",
            # Chunk 3: ratio / calculation note
            "Revenue: $850,000\nGross profit: $340,000\n"
            "Gross profit margin: 40.00%\n"
            "Gross profit divided by Revenue",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is not None, "calculation returned None for the trace scenario"
        assert "40.00%" in proof.answer
        assert "FY2025" in proof.answer
        assert proof.reporting_period == "2025"

    def test_cross_check_with_explicit_ratio(self):
        """When an explicit ratio is in the doc, the calculated value must match."""
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000\n"
            "Gross profit: $340,000\nGross profit margin: 40.00%",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer
        # The explicit ratio in the passage is 40.00%.
        # The independent calculation: 340000 / 850000 * 100 = 40.00%
        # They match — this is the cross-check the requirements demand.


# ---------------------------------------------------------------------------
# 9) Non-data label mentions do NOT invalidate.
# ---------------------------------------------------------------------------


class TestNonDataMentions:
    """Labels in descriptive text, formulas, or headings must not invalidate."""

    @pytest.mark.parametrize(
        "descriptive_line",
        [
            "Gross profit divided by Revenue",
            "Revenue growth was driven by new markets",
            "Total revenue increased year over year",
            "Net income reflects strong cost management",
            "Operating income improved due to efficiency gains",
            "Total assets include both current and non-current items",
        ],
    )
    def test_descriptive_mention_does_not_invalidate(self, descriptive_line):
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000\nCOGS: $510,000",
            descriptive_line,
        )
        proof = calculate(QUESTION, evidence)
        assert proof is not None, (
            f"descriptive line '{descriptive_line}' caused abstention"
        )
        assert "40.00%" in proof.answer

    def test_section_heading_does_not_invalidate_same_chunk(self):
        """A section heading like 'Revenue Analysis' in the same chunk before data rows must not invalidate."""
        evidence = _make_evidence(
            "Northstar Components FY2025\n"
            "Revenue Analysis\n"
            "Revenue: $850,000\n"
            "COGS: $510,000",
        )
        facts, invalid = extract_calculation_inputs(evidence)
        assert "revenue" in facts, f"revenue missing; invalid={invalid}"
        assert facts["revenue"].amount == Decimal(850000)
        assert "revenue" not in invalid
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer

    def test_section_heading_does_not_invalidate_cross_chunk(self):
        """A section heading in a separate chunk must not invalidate."""
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue Analysis",
            "Revenue: $850,000\nCOGS: $510,000",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer

    def test_split_cells_and_table_separators_with_descriptive_headings(self):
        """Verify multiline rows with pipe separators and adjacent descriptive headers."""
        evidence = _make_evidence(
            "Northstar Components FY2025\n"
            "Executive Overview\n"
            "| Revenue | $850,000 |\n"
            "| Cost of goods sold (COGS) | $510,000 |\n"
            "Gross profit divided by revenue was 40%",
        )
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer
        assert proof.sources == (1,)

    def test_malformed_multiple_monetary_values_abstains(self):
        """A row with multiple monetary values is ambiguous and must cause abstention."""
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: $850,000 $700,000\nCOGS: $510,000",
        )
        _facts, invalid = extract_calculation_inputs(evidence)
        assert "revenue" in invalid
        proof = calculate(QUESTION, evidence)
        assert proof is None

    def test_formula_with_math_operators_and_numbers_does_not_invalidate(self):
        """Formulas mentioning labels with math operators (e.g. 'Gross profit minus operating expenses = $160,000') must not invalidate."""
        evidence = _make_evidence(
            "Northstar Components FY2025\n"
            "Revenue\n$850,000\n"
            "Cost of goods sold (COGS)\n$510,000\n"
            "Gross profit\n$340,000\n"
            "Calculation checks: Gross profit = Revenue minus COGS = $850,000 minus $510,000 = $340,000.\n"
            "Gross profit minus operating expenses = $160,000.",
        )
        facts, invalid = extract_calculation_inputs(evidence)
        assert "gross profit" in facts
        assert facts["gross profit"].amount == Decimal(340000)
        assert "gross profit" not in invalid
        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer

    def test_full_live_trace_document_passages_succeed(self):
        """Reproduce the exact text passages from the live production trace."""
        chunk1 = (
            "NORTHSTAR COMPONENTS\n"
            "Illustrative Financial Statements & Management Analysis\n"
            "Financial year ended 31 December 2025\n"
            "Revenue\nNet income\nTotal assets\n\n"
            "$850,000\n$96,000\n$600,000\n\n"
            "All amounts are in US dollars (USD).\n\n"
            "1. Executive Summary\n"
            "During FY2025, the company generated revenue of $850,000 and net income of $96,000. "
            "Gross profit was $340,000, representing a gross profit margin of 40.0%. "
            "The company ended the year with total assets of $600,000 and total liabilities of $360,000.\n\n"
            "2. Income Statement\n"
            "For the year ended 31 December 2025\n"
            "Revenue\n$850,000\n"
            "Cost of goods sold (COGS)\n$510,000\n"
            "Gross profit\n$340,000\n"
            "Operating expenses\n$180,000\n"
            "Operating income\n$160,000\n"
            "Net income\n$96,000\n"
            "Calculation checks: Gross profit = Revenue minus COGS = $850,000 minus $510,000 = $340,000. "
            "Operating income = Gross profit minus operating expenses = $160,000.\n"
            "3. Balance Sheet\n"
            "Total assets\n$600,000\n"
            "Total liabilities\n$360,000"
        )
        chunk2 = (
            "5. Selected Financial Ratios\n"
            "Gross profit margin\n"
            "Gross profit / Revenue x 100\n"
            "40.00%\n\n"
            "Operating margin\n"
            "Operating income / Revenue x 100\n"
            "18.82%\n\n"
            "Net profit margin\n"
            "Net income / Revenue x 100\n"
            "11.29%\n\n"
            "Debt-to-assets\n"
            "Total liabilities / Total assets x 100\n"
            "60.00%\n\n"
            "Current assets\n"
            "Cash + Receivables + Inventory\n"
            "$300,000\n\n"
            "Current ratio\n"
            "Current assets / Current liabilities\n"
            "1.875x\n"
            "Current liabilities are accounts payable of $90,000 plus short-term borrowings of $70,000, totaling $160,000."
        )
        evidence = _make_evidence(chunk1, chunk2)
        facts, invalid = extract_calculation_inputs(evidence)
        assert "revenue" in facts and facts["revenue"].amount == Decimal(850000)
        assert "COGS" in facts and facts["COGS"].amount == Decimal(510000)
        assert "gross profit" in facts and facts["gross profit"].amount == Decimal(
            340000
        )
        assert not (invalid & {"revenue", "COGS", "gross profit"})

        proof = calculate(QUESTION, evidence)
        assert proof is not None
        assert "40.00%" in proof.answer
        assert "FY2025" in proof.answer

        ver = EvidenceVerifier().verify(
            QUESTION,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert ver.evidence_status == EvidenceStatus.SUFFICIENT

        cv = ClaimVerifier().verify(proof.answer, evidence)
        assert cv.overall_status == ClaimOverallStatus.VERIFIED

    def test_missing_currency_abstains(self):
        """Rows without valid currency units cannot be assumed to be USD."""
        evidence = _make_evidence(
            "Northstar Components FY2025\nRevenue: 850,000\nCOGS: 510,000",
        )
        facts, _invalid = extract_calculation_inputs(evidence)
        assert "revenue" not in facts
        proof = calculate(QUESTION, evidence)
        assert proof is None


# ---------------------------------------------------------------------------
# 10) Existing calculation, evidence-verification, and provenance tests
#     remain green (covered by running the full test suite).
# ---------------------------------------------------------------------------
