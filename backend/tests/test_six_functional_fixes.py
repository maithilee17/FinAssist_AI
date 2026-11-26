"""Regression tests for the six live functional test failures on Northstar Components FY2025.

Test 5: Total assets in FY2025 ($600,000) — Page scoring and evidence verification
Test 9: Debt-to-assets ratio calculation (60.00%)
Test 10: Current ratio calculation (1.875x)
Test 12: Cash flow summary completeness and net change in cash calculation ($25,000)
Test 14: Financial and operational risk identification (QueryType.CONCEPTUAL and SUFFICIENT evidence)
Test 17: Ambiguous 'profit margin' query clarification request
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.services.adaptive_retrieval import RetrievalDiagnostics, RetrievalStrategy
from app.services.claim_verifier import ClaimOverallStatus, ClaimStatus, ClaimVerifier
from app.services.confidence_service import ConfidenceAssessment
from app.services.evidence_page_selector import EvidencePageSelector
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import (
    calculate,
    calculation_kind,
    extract_calculation_inputs,
)
from app.services.query_analyzer import FinancialQueryAnalyzer, QueryType
from app.services.question_requirements import QuestionRequirementAnalyzer
from app.services.rag_pipeline import ABSTENTION_ANSWER, RagPipeline
from app.services.vector_store import VectorSearchResult

NORTHSTAR_CHUNK_0 = """NORTHSTAR COMPONENTS

Illustrative Financial Statements & Management Analysis

Financial year ended 31 December 2025

Revenue
Net income
Total assets

$850,000
$96,000
$600,000

Demonstration document: Northstar Components is fictional. All financial figures and commentary are invented for testing
FinAssist AI document upload, extraction, indexing, retrieval, and question answering. This is not an audited report and must
not be used for financial decisions.

All amounts are in US dollars (USD).

NORTHSTAR COMPONENTS | FICTIONAL DEMONSTRATION
Page 1

1. Executive Summary

Northstar Components is a fictional mid-sized manufacturer of industrial electrical components. During FY2025, the company
generated revenue of $850,000 and net income of $96,000. Gross profit was $340,000, representing a gross profit margin of
40.0%. The company ended the year with total assets of $600,000 and total liabilities of $360,000.

Management attributes revenue growth to higher unit sales to existing distributors and the launch of two upgraded product
lines. Operating expenses increased due to additional engineering staff and freight costs. These statements are illustrative
and unaudited.

2. Income Statement

For the year ended 31 December 2025

Line item
FY2025 (USD)

Revenue
$850,000

Cost of goods sold (COGS)
$510,000

Gross profit
$340,000

Operating expenses
$180,000

Operating income
$160,000

Interest expense
$24,000

Income tax expense
$40,000

Net income
$96,000

Calculation checks: Gross profit = Revenue minus COGS = $850,000 minus $510,000 = $340,000. Operating income =
Gross profit minus operating expenses = $160,000. Net income = Operating income minus interest expense minus income
tax expense = $96,000.

3. Balance Sheet

As at 31 December 2025

Assets
FY2025 (USD)

Cash and cash equivalents
$75,000

Accounts receivable
$105,000

Inventory
$120,000

Property, plant and equipment, net
$300,000

Total assets
$600,000

Liabilities and equity
FY2025 (USD)

Accounts payable
$90,000

Short-term borrowings
$70,000

Long-term debt
$200,000

Total liabilities
$360,000

NORTHSTAR COMPONENTS | FICTIONAL DEMONSTRATION
Page 2
"""

NORTHSTAR_CHUNK_1 = """NORTHSTAR COMPONENTS | FICTIONAL DEMONSTRATION
Page 3

4. Cash Flow Summary

Cash flow item
FY2025 (USD)

Net cash from operating activities
$118,000

Net cash used in investing activities
($65,000)

Net cash used in financing activities
($28,000)

Net increase in cash
$25,000

Cash at beginning of year
$50,000

Cash at end of year
$75,000

Cash increased by $25,000 during FY2025, from $50,000 to $75,000. Operating activities generated $118,000 in net cash.
Investing activities used $65,000, primarily for production equipment. Financing activities used $28,000, reflecting scheduled
debt repayments.

5. Selected Financial Ratios

Metric
Formula
FY2025

Gross profit margin
Gross profit / Revenue x 100
40.00%

Operating margin
Operating income / Revenue x 100
18.82%

Net profit margin
Net income / Revenue x 100
11.29%

Debt-to-assets
Total liabilities / Total assets x 100
60.00%

Current assets
Cash + Receivables + Inventory
$300,000

Current ratio
Current assets / Current liabilities
1.875x

Current liabilities are accounts payable of $90,000 plus short-term borrowings of $70,000, totaling $160,000. Current assets
are $300,000. Therefore, the current ratio is 1.875 times.

6. Management Commentary and Risks

Liquidity: The current ratio of 1.875x indicates current assets exceed current liabilities at year-end. Inventory represents
$120,000 of current assets, so the timing of inventory conversion may affect near-term liquidity.

Leverage: Total liabilities are 60.0% of total assets. Long-term debt of $200,000 is the largest individual liability category.

Profitability: The company reported an 11.29% net profit margin. Interest expense of $24,000 reduces income before tax.

Operating risks: Potential risks include raw-material price volatility, customer concentration, freight cost increases, inventory
obsolescence, and refinancing risk. No probability or quantified loss estimate is provided.

7. Notes and Data Limitations
"""


def _make_northstar_evidence():
    user_id = uuid4()
    document_id = uuid4()
    return [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="FinAssist_Sample_Financial_Report.pdf",
            page_numbers=[1, 2],
            chunk_text=NORTHSTAR_CHUNK_0,
            similarity_score=0.88,
        ),
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="FinAssist_Sample_Financial_Report.pdf",
            page_numbers=[3, 4],
            chunk_text=NORTHSTAR_CHUNK_1,
            similarity_score=0.85,
        ),
    ]


# ===========================================================================
# Test 5: Total Assets in FY2025 ($600,000)
# ===========================================================================


class Test5TotalAssetsFix:
    """Verify that Page 2 (Balance Sheet) is prioritized over Page 4 (Formulas/Notes)

    and evidence verification accurately accepts $600,000 total assets.
    """

    def test_page_scoring_prioritizes_balance_sheet_over_formula_notes(self):
        question = "What were the total assets in FY2025?"
        selector = EvidencePageSelector()
        requirements = QuestionRequirementAnalyzer().analyze(question)

        # Page 2 has the actual balance sheet row
        page_2_text = (
            "Northstar Components FY2025\n"
            "3. Balance Sheet\n"
            "Total assets\n$600,000\n"
            "Total liabilities\n$360,000"
        )
        # Page 4 has ratio notes mentioning Total Assets in formula and cash flow numbers
        page_4_text = (
            "Northstar Components FY2025\n"
            "5. Selected Financial Ratios\n"
            "Debt-to-assets\n"
            "Total liabilities / Total assets x 100\n"
            "60.00%\n"
            "Operating cash flow $118,000"
        )

        score_p2, has_val_p2 = selector._score_page(question, page_2_text, requirements)
        score_p4, _has_val_p4 = selector._score_page(
            question, page_4_text, requirements
        )

        assert score_p2 > score_p4, (
            f"Page 2 ({score_p2}) must rank above Page 4 ({score_p4})"
        )
        assert has_val_p2 is True

    def test_evidence_verifier_sufficient_for_balance_sheet_assets(self):
        evidence = _make_northstar_evidence()
        question = "What were the total assets in FY2025?"
        verifier = EvidenceVerifier()
        result = verifier.verify(
            question,
            [evidence[0]],  # Chunk 0 contains Page 2 balance sheet
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status == EvidenceStatus.SUFFICIENT
        assert "2025 total assets" in result.supported_aspects
        assert not result.missing_aspects

    def test_extracted_total_assets_amount(self):
        evidence = _make_northstar_evidence()
        facts, invalid = extract_calculation_inputs(evidence)
        assert "total assets" in facts
        assert facts["total assets"].amount == Decimal(600000)
        assert facts["total assets"].currency == "USD"
        assert "total assets" not in invalid


# ===========================================================================
# Test 9: Debt-to-Assets Ratio (60.00%)
# ===========================================================================


class Test9DebtToAssetsCalculationFix:
    """Calculate debt-to-assets ratio for FY2025 = 60.00%."""

    def test_debt_to_assets_calculation_succeeds(self):
        evidence = _make_northstar_evidence()
        question = "Calculate the debt-to-assets ratio for FY2025. Show the supporting figures and formula."
        proof = calculate(question, evidence)
        assert proof is not None
        assert "60.00%" in proof.answer
        assert "360000 / 600000 * 100 = 60.00%" in proof.answer
        assert {fact.label for fact in proof.inputs} == {
            "total liabilities",
            "total assets",
        }
        assert {fact.amount for fact in proof.inputs} == {
            Decimal(360000),
            Decimal(600000),
        }
        # Check claim verification succeeds on the exact proof answer
        checked = ClaimVerifier().verify(proof.answer, evidence)
        assert checked.overall_status == ClaimOverallStatus.VERIFIED

    def test_debt_to_assets_conflicting_inputs_abstains(self):
        user_id = uuid4()
        document_id = uuid4()
        conflicting_evidence = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="FinAssist_Sample_Financial_Report.pdf",
                page_numbers=[2],
                chunk_text="Northstar Components FY2025\nTotal assets: $600,000\nTotal liabilities: $360,000",
                similarity_score=0.9,
            ),
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="FinAssist_Sample_Financial_Report.pdf",
                page_numbers=[3],
                chunk_text="Northstar Components FY2025\nTotal liabilities: $400,000",
                similarity_score=0.9,
            ),
        ]
        question = "Calculate the debt-to-assets ratio for FY2025."
        assert calculate(question, conflicting_evidence) is None

    def test_debt_to_assets_missing_liability_abstains(self):
        user_id = uuid4()
        document_id = uuid4()
        missing_evidence = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="FinAssist_Sample_Financial_Report.pdf",
                page_numbers=[2],
                chunk_text="Northstar Components FY2025\nTotal assets: $600,000",
                similarity_score=0.9,
            )
        ]
        question = "Calculate the debt-to-assets ratio for FY2025."
        assert calculate(question, missing_evidence) is None


# ===========================================================================
# Test 10: Current Ratio Calculation (1.875x)
# ===========================================================================


class Test10CurrentRatioCalculationFix:
    """Calculate current ratio for FY2025 = 300,000 / 160,000 = 1.875x."""

    def test_current_ratio_calculation_succeeds(self):
        evidence = _make_northstar_evidence()
        question = "Calculate the current ratio for FY2025. Show current assets, current liabilities and the calculation."
        assert calculation_kind(question) == "current ratio"
        proof = calculate(question, evidence)
        assert proof is not None
        assert "1.875" in proof.answer
        assert "300000 / 160000 = 1.875" in proof.answer
        assert {fact.label for fact in proof.inputs} == {
            "current assets",
            "current liabilities",
        }
        assert {fact.amount for fact in proof.inputs} == {
            Decimal(300000),
            Decimal(160000),
        }
        # Check claim verification succeeds
        checked = ClaimVerifier().verify(proof.answer, evidence)
        assert checked.overall_status == ClaimOverallStatus.VERIFIED

    def test_current_ratio_conflicting_inputs_abstains(self):
        user_id = uuid4()
        document_id = uuid4()
        conflicting_evidence = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="report.pdf",
                page_numbers=[4],
                chunk_text="Current assets: $300,000\nCurrent liabilities: $160,000",
                similarity_score=0.9,
            ),
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="report.pdf",
                page_numbers=[5],
                chunk_text="Current assets: $350,000",
                similarity_score=0.9,
            ),
        ]
        question = "Calculate the current ratio for FY2025."
        assert calculate(question, conflicting_evidence) is None

    def test_current_ratio_missing_liabilities_abstains(self):
        user_id = uuid4()
        document_id = uuid4()
        missing_evidence = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="report.pdf",
                page_numbers=[4],
                chunk_text="Current assets: $300,000",
                similarity_score=0.9,
            )
        ]
        question = "Calculate the current ratio for FY2025."
        assert calculate(question, missing_evidence) is None


# ===========================================================================
# Test 12: Cash Flow Summary & Net Change in Cash
# ===========================================================================


class Test12CashFlowFix:
    """Cash flow summary completeness and net change in cash calculation."""

    def test_net_change_in_cash_calculation(self):
        evidence = _make_northstar_evidence()
        question = "Calculate the net change in cash for FY2025."
        assert calculation_kind(question) == "net change in cash"
        proof = calculate(question, evidence)
        assert proof is not None
        assert "25000" in proof.answer
        assert "75000 - 50000 = 25000.00 USD" in proof.answer
        assert {fact.label for fact in proof.inputs} == {
            "ending cash",
            "beginning cash",
        }
        assert {fact.amount for fact in proof.inputs} == {
            Decimal(75000),
            Decimal(50000),
        }
        checked = ClaimVerifier().verify(proof.answer, evidence)
        assert checked.overall_status == ClaimOverallStatus.VERIFIED

    def test_cash_flow_summary_system_instruction_mentions_net_change(self):
        from app.services.rag_pipeline import SYSTEM_INSTRUCTION

        assert (
            "along with the net change (increase or decrease) in cash"
            in SYSTEM_INSTRUCTION
        )


# ===========================================================================
# Test 13: Ending Cash Reconciliation
# ===========================================================================


class Test13EndingCashReconciliationFix:
    """Ending cash reconciliation: all three dollar amounts, addition formula, citations, and discrepancy checks."""

    QUESTION_1 = (
        "Reconcile the beginning cash balance to the ending cash balance for "
        "Northstar Components in FY2025. Show beginning cash, net increase in "
        "cash, ending cash, the calculation, and supporting citations from the "
        "uploaded report."
    )
    QUESTION_2 = (
        "For FY2025, reconcile Northstar Components' cash balance using the formula: "
        "Ending Cash = Beginning Cash + Net Increase in Cash. Show all three dollar "
        "amounts, substitute them into this exact formula, and cite the supporting "
        "financial report evidence."
    )

    def test_ending_cash_reconciliation_question_1(self):
        evidence = _make_northstar_evidence()
        analyzer = FinancialQueryAnalyzer()
        analysis = analyzer.analyze(self.QUESTION_1)
        assert analysis.query_type == QueryType.CALCULATION
        assert calculation_kind(self.QUESTION_1) == "ending cash reconciliation"

        proof = calculate(self.QUESTION_1, evidence)
        assert proof is not None
        assert proof.discrepancy is False
        assert "Beginning cash = $50,000" in proof.answer
        assert "Net cash increase = $25,000" in proof.answer
        assert "Ending cash = $75,000" in proof.answer
        assert "Ending Cash = Beginning Cash + Net Increase in Cash" in proof.answer
        assert "$75,000 = $50,000 + $25,000" in proof.answer
        assert "[Source" in proof.answer

        assert {fact.label for fact in proof.inputs} == {
            "beginning cash",
            "net cash increase",
            "ending cash",
        }
        assert {fact.amount for fact in proof.inputs} == {
            Decimal(50000),
            Decimal(25000),
            Decimal(75000),
        }

        checked = ClaimVerifier().verify(
            proof.answer, evidence, question=self.QUESTION_1
        )
        assert checked.overall_status == ClaimOverallStatus.VERIFIED

    def test_ending_cash_reconciliation_question_2(self):
        evidence = _make_northstar_evidence()
        analyzer = FinancialQueryAnalyzer()
        analysis = analyzer.analyze(self.QUESTION_2)
        assert analysis.query_type == QueryType.CALCULATION
        assert calculation_kind(self.QUESTION_2) == "ending cash reconciliation"

        proof = calculate(self.QUESTION_2, evidence)
        assert proof is not None
        assert proof.discrepancy is False
        assert "Beginning cash = $50,000" in proof.answer
        assert "Net cash increase = $25,000" in proof.answer
        assert "Ending cash = $75,000" in proof.answer
        assert "Ending Cash = Beginning Cash + Net Increase in Cash" in proof.answer
        assert "$75,000 = $50,000 + $25,000" in proof.answer

        checked = ClaimVerifier().verify(
            proof.answer, evidence, question=self.QUESTION_2
        )
        assert checked.overall_status == ClaimOverallStatus.VERIFIED

    def test_net_change_in_cash_remains_independent(self):
        evidence = _make_northstar_evidence()
        question = "Calculate the net change in cash for FY2025."
        assert calculation_kind(question) == "net change in cash"

        proof = calculate(question, evidence)
        assert proof is not None
        assert (
            "ending cash - beginning cash = 75000 - 50000 = 25000.00 USD"
            in proof.answer
        )

        checked = ClaimVerifier().verify(proof.answer, evidence, question=question)
        assert checked.overall_status == ClaimOverallStatus.VERIFIED

    def test_nonresponsive_calculation_rejected_by_claim_verifier(self):
        evidence = _make_northstar_evidence()
        question_net = "Calculate the net change in cash for FY2025."
        proof_net = calculate(question_net, evidence)
        assert proof_net is not None

        # Pass net change calculation answer to ending cash reconciliation question
        checked = ClaimVerifier().verify(
            proof_net.answer, evidence, question=self.QUESTION_1
        )
        assert checked.overall_status != ClaimOverallStatus.VERIFIED
        assert checked.overall_status == ClaimOverallStatus.UNSUPPORTED
        assert "nonresponsive" in checked.claims[0].reason

    def test_missing_inputs_abstains(self):
        user_id = uuid4()
        doc_id = uuid4()

        # Missing beginning cash
        ev_no_beg = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nNet increase in cash: $25,000\nCash at end of year: $75,000",
                similarity_score=0.9,
            )
        ]
        assert calculate(self.QUESTION_1, ev_no_beg) is None

        # Missing ending cash
        ev_no_end = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nCash at beginning of year: $50,000\nNet increase in cash: $25,000",
                similarity_score=0.9,
            )
        ]
        assert calculate(self.QUESTION_1, ev_no_end) is None

        # Missing net increase
        ev_no_net = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nCash at beginning of year: $50,000\nCash at end of year: $75,000",
                similarity_score=0.9,
            )
        ]
        assert calculate(self.QUESTION_1, ev_no_net) is None

    def test_mismatched_balances_reports_discrepancy_and_not_verified(self):
        user_id = uuid4()
        doc_id = uuid4()
        ev_mismatched = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text=(
                    "FY2025\n"
                    "Cash at beginning of year: $50,000\n"
                    "Net increase in cash: $25,000\n"
                    "Cash at end of year: $80,000"
                ),
                similarity_score=0.9,
            )
        ]
        proof = calculate(self.QUESTION_1, ev_mismatched)
        assert proof is not None
        assert proof.discrepancy is True
        assert "Discrepancy in ending cash reconciliation" in proof.answer
        assert "Calculated: $75,000 != Reported: $80,000" in proof.answer

        checked = ClaimVerifier().verify(
            proof.answer, ev_mismatched, question=self.QUESTION_1
        )
        assert checked.overall_status != ClaimOverallStatus.VERIFIED
        assert checked.overall_status == ClaimOverallStatus.UNSUPPORTED

    def test_conflicting_currencies_abstains(self):
        user_id = uuid4()
        doc_id = uuid4()
        ev_conflict = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text=(
                    "FY2025\n"
                    "Cash at beginning of year: $50,000\n"
                    "Net increase in cash: €25,000\n"
                    "Cash at end of year: $75,000"
                ),
                similarity_score=0.9,
            )
        ]
        assert calculate(self.QUESTION_1, ev_conflict) is None

    def test_mismatched_reporting_period_abstains(self):
        user_id = uuid4()
        doc_id = uuid4()
        ev_period = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text=(
                    "FY2024\n"
                    "Cash at beginning of year: $50,000\n"
                    "Net increase in cash: $25,000\n"
                    "Cash at end of year: $75,000"
                ),
                similarity_score=0.9,
            )
        ]
        assert calculate(self.QUESTION_1, ev_period) is None

    def test_cross_document_ownership_abstains(self):
        user_id = uuid4()
        doc_id_1 = uuid4()
        doc_id_2 = uuid4()
        ev_cross_doc = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id_1,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nCash at beginning of year: $50,000\nNet increase in cash: $25,000",
                similarity_score=0.9,
            ),
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id_2,
                filename="report2.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nCash at end of year: $75,000",
                similarity_score=0.9,
            ),
        ]
        assert calculate(self.QUESTION_1, ev_cross_doc) is None

        # Cross-user
        user_id_2 = uuid4()
        ev_cross_user = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=doc_id_1,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nCash at beginning of year: $50,000\nNet increase in cash: $25,000",
                similarity_score=0.9,
            ),
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id_2,
                document_id=doc_id_1,
                filename="report.pdf",
                page_numbers=[3],
                chunk_text="FY2025\nCash at end of year: $75,000",
                similarity_score=0.9,
            ),
        ]
        assert calculate(self.QUESTION_1, ev_cross_user) is None


# ===========================================================================
# Test 14: Risk Factors (Conceptual Query & Evidence Verification)
# ===========================================================================


class Test14RiskFactorsFix:
    """Query type is CONCEPTUAL and evidence verifier marks risk query SUFFICIENT."""

    def test_live_risk_query_classified_as_conceptual_and_hybrid(self):
        from app.services.adaptive_retrieval import (
            AdaptiveRetrievalSelector,
            RetrievalStrategy,
        )

        question = (
            "List each financial and operational risk explicitly mentioned in the "
            "FY2025 Northstar Components report. Give the risk name, a brief explanation "
            "based only on the document, and its source citation. Do not omit any listed risk."
        )
        analyzer = FinancialQueryAnalyzer()
        analysis = analyzer.analyze(question)
        assert analysis.query_type == QueryType.CONCEPTUAL, (
            f"Expected QueryType.CONCEPTUAL, got {analysis.query_type}"
        )
        assert analysis.requires_semantic_context is True
        assert analysis.has_exact_terms is True

        selector = AdaptiveRetrievalSelector()
        selection = selector.select(analysis)
        assert selection.selected_strategy == RetrievalStrategy.HYBRID

    def test_paraphrased_risk_queries_are_conceptual(self):
        from app.services.adaptive_retrieval import (
            AdaptiveRetrievalSelector,
            RetrievalStrategy,
        )

        analyzer = FinancialQueryAnalyzer()
        selector = AdaptiveRetrievalSelector()
        paraphrases = [
            "Identify the major financial and operational risks mentioned in the Northstar Components FY2025 report. Explain each risk briefly and cite the supporting evidence.",
            "Enumerate all operational and financial risks described in Northstar Components FY2025.",
            "Describe the key business risks disclosed in the FY2025 report.",
            "Explain the financial and operational risks facing Northstar Components.",
        ]
        for q in paraphrases:
            analysis = analyzer.analyze(q)
            assert analysis.query_type == QueryType.CONCEPTUAL, (
                f"Query '{q}' expected CONCEPTUAL, got {analysis.query_type}"
            )
            selection = selector.select(analysis)
            assert selection.selected_strategy in (
                RetrievalStrategy.HYBRID,
                RetrievalStrategy.SEMANTIC,
            )

    def test_numeric_queries_with_list_or_identify_not_misclassified(self):
        analyzer = FinancialQueryAnalyzer()
        q1 = "List the total revenue and net income for FY2025."
        q2 = "Identify the total assets for FY2025."
        assert analyzer.analyze(q1).query_type == QueryType.FINANCIAL_METRIC
        assert analyzer.analyze(q2).query_type == QueryType.FINANCIAL_METRIC

    def test_live_risk_evidence_verifier_sufficient(self):
        evidence = _make_northstar_evidence()
        question = (
            "List each financial and operational risk explicitly mentioned in the "
            "FY2025 Northstar Components report. Give the risk name, a brief explanation "
            "based only on the document, and its source citation. Do not omit any listed risk."
        )
        verifier = EvidenceVerifier()
        result = verifier.verify(
            question,
            [evidence[1]],  # Chunk 1 contains Section 6 Management Commentary and Risks
            user_id=evidence[1].user_id,
            allowed_document_ids={evidence[1].document_id},
        )
        assert result.evidence_status == EvidenceStatus.SUFFICIENT, (
            f"Expected SUFFICIENT, got {result.evidence_status} with reason: {result.reason}"
        )
        assert result.relevance_score >= 0.70
        assert result.sufficiency_score >= 0.70
        assert not result.missing_aspects

    def test_document_lacking_risk_disclosures_abstains(self):
        user_id = uuid4()
        document_id = uuid4()
        no_risk_evidence = [
            VectorSearchResult(
                chunk_id=uuid4(),
                user_id=user_id,
                document_id=document_id,
                filename="No_Risk_Report.pdf",
                page_numbers=[1],
                chunk_text="Northstar Components FY2025\nRevenue was $850,000. COGS was $510,000.",
                similarity_score=0.85,
            )
        ]
        question = "List each financial and operational risk mentioned in FY2025."
        verifier = EvidenceVerifier()
        result = verifier.verify(
            question,
            no_risk_evidence,
            user_id=user_id,
            allowed_document_ids={document_id},
        )
        assert result.evidence_status != EvidenceStatus.SUFFICIENT
        assert "risk" in result.missing_aspects

    def test_complete_generated_answer_claim_verification(self):
        evidence = _make_northstar_evidence()
        d = "$"
        full_answer = (
            "The Northstar Components FY2025 report discloses five operating risks [Source 2]:\n"
            "1. Raw-material price volatility: potential operating risk with no probability or quantified loss estimate provided [Source 2].\n"
            "2. Customer concentration: potential operating risk with unit sales dependent on existing distributors [Source 2].\n"
            "3. Freight cost increases: potential operating risk contributing to higher operating expenses [Source 2].\n"
            f"4. Inventory obsolescence: potential risk where inventory of {d}120,000 may affect near-term liquidity [Source 2].\n"
            f"5. Refinancing risk: potential risk where long-term debt of {d}200,000 represents the largest liability category [Source 2]."
        )
        claim_verifier = ClaimVerifier()
        verification = claim_verifier.verify(full_answer, evidence)
        assert verification.overall_status == ClaimOverallStatus.VERIFIED
        assert verification.supported_claims == verification.claims_checked
        assert verification.unsupported_claims == 0

    def test_unsupported_invented_risk_caught_as_unsupported(self):
        evidence = _make_northstar_evidence()
        answer_with_fake_risk = (
            "Northstar Components identified the following operating risks [Source 2]:\n"
            "1. Raw-material price volatility: potential operating risk [Source 2].\n"
            "2. Foreign currency volatility: catastrophic exchange rate losses [Source 2]."
        )
        claim_verifier = ClaimVerifier()
        verification = claim_verifier.verify(answer_with_fake_risk, evidence)
        assert verification.overall_status != ClaimOverallStatus.VERIFIED
        fake_claim = next(
            c for c in verification.claims if "Foreign currency" in c.claim
        )
        assert fake_claim.status == ClaimStatus.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_end_to_end_rag_pipeline_risk_answer(self):
        evidence = _make_northstar_evidence()
        mock_retrieval = MagicMock()
        mock_diagnostics = RetrievalDiagnostics(
            selected_strategy=RetrievalStrategy.HYBRID,
            selection_reason="Hybrid retrieval test.",
            query_analysis={"query_type": "conceptual"},
            keyword_result_count=len(evidence),
            semantic_result_count=len(evidence),
            fusion_result_count=len(evidence),
            retrieved_chunks_count=len(evidence),
            retrieval_time_ms=5.0,
        )
        mock_retrieval.retrieve = AsyncMock(
            return_value=MagicMock(
                retrieved_chunks=[evidence[1]],
                diagnostics=mock_diagnostics,
            )
        )
        mock_page_selector = MagicMock()
        mock_page_selector.refine = AsyncMock(return_value=[evidence[1]])

        mock_llm = MagicMock()
        mock_llm.model_name = "test-ollama-qwen"
        d = "$"
        risk_answer = (
            "The Northstar Components FY2025 report identifies five operating risks [Source 1]:\n"
            "1. Raw-material price volatility: potential operating risk with no probability or quantified loss estimate provided [Source 1].\n"
            "2. Customer concentration: potential operating risk with unit sales dependent on existing distributors [Source 1].\n"
            "3. Freight cost increases: potential operating risk contributing to higher operating expenses [Source 1].\n"
            f"4. Inventory obsolescence: potential risk where inventory of {d}120,000 may affect near-term liquidity [Source 1].\n"
            f"5. Refinancing risk: potential risk where long-term debt of {d}200,000 represents the largest liability category [Source 1]."
        )
        mock_llm.generate = AsyncMock(
            return_value=MagicMock(
                answer=risk_answer,
                model_name="test-ollama-qwen",
            )
        )

        pipeline = RagPipeline(
            retrieval_service=mock_retrieval,
            llm_service=mock_llm,
            evidence_verifier=EvidenceVerifier(),
            confidence_service=ConfidenceAssessment,
            page_selector=mock_page_selector,
        )
        pipeline._allowed_document_ids = AsyncMock(
            return_value=[evidence[1].document_id]
        )

        from app.services.confidence_service import ConfidenceService

        pipeline.confidence_service = ConfidenceService()

        mock_db = AsyncMock()
        q = (
            "List each financial and operational risk explicitly mentioned in the "
            "FY2025 Northstar Components report. Give the risk name, a brief explanation "
            "based only on the document, and its source citation. Do not omit any listed risk."
        )
        res = await pipeline.answer(
            mock_db,
            user_id=evidence[1].user_id,
            question=q,
            document_ids=[evidence[1].document_id],
        )

        assert res.verification.overall_status == "verified"
        assert res.confidence.level == "high"
        assert "raw-material price volatility" in res.answer.lower()
        assert "customer concentration" in res.answer.lower()
        assert "freight cost increases" in res.answer.lower()
        assert "inventory obsolescence" in res.answer.lower()
        assert "refinancing risk" in res.answer.lower()

    def test_all_five_risks_present_in_chunk(self):
        text = " ".join(NORTHSTAR_CHUNK_1.lower().split())
        expected_risks = [
            "raw-material price volatility",
            "customer concentration",
            "freight cost increases",
            "inventory obsolescence",
            "refinancing risk",
        ]
        for risk in expected_risks:
            assert risk in text, f"Missing risk mention: {risk}"

    def test_out_of_bounds_section_number_citation_fails_verification(self):
        evidence = _make_northstar_evidence()
        failed_response = (
            "The major financial and operational risks mentioned in the Northstar Components FY2025 report are:\n\n"
            "- Raw-material price volatility: This poses a risk to cost control and profitability, as fluctuations in raw material prices could increase production costs without corresponding increases in revenue [Source 6].\n"
            "- Customer concentration: The report identifies this as a risk, implying that reliance on a small number of customers could expose the company to significant revenue loss if those customers reduce orders or discontinue business [Source 6].\n"
            "- Freight cost increases: Rising freight costs could erode profit margins, especially if such increases are not offset by price adjustments or cost efficiencies [Source 6].\n"
            "- Inventory obsolescence: The risk that inventory may become outdated or unsellable could lead to write-downs and reduced asset values, impacting liquidity and profitability [Source 6].\n"
            "- Refinancing risk: The company faces the risk of being unable to refinance long-term debt, which could result in financial distress or default [Source 6].\n\n"
            "No probability or quantified loss estimate is provided for any of these risks [Source 6]."
        )
        claim_verifier = ClaimVerifier()
        verification = claim_verifier.verify(failed_response, evidence)
        assert verification.overall_status == ClaimOverallStatus.UNSUPPORTED
        assert verification.claims_checked == 6
        assert verification.supported_claims == 0
        assert verification.unsupported_claims == 6
        assert all(not c.citation_valid for c in verification.claims)
        assert all(c.status == ClaimStatus.UNSUPPORTED for c in verification.claims)

    def test_multi_sentence_bullet_risk_answer_verified(self):
        evidence = _make_northstar_evidence()
        multi_sentence_response = (
            "The major financial and operational risks mentioned in the Northstar Components FY2025 report are:\n\n"
            "- Raw-material price volatility: This poses a risk to cost control and profitability. The report identifies this as a potential operational risk, though no probability or quantified loss estimate is provided [Source 2].\n"
            "- Customer concentration: The report identifies this as a risk. Reliance on a small number of customers could expose the company to significant revenue loss [Source 2].\n"
            "- Freight cost increases: Rising freight costs could increase operating expenses. This affects profitability and cash flow [Source 2].\n"
            "- Inventory obsolescence: The risk of inventory becoming outdated or unsellable is noted. It could lead to write-downs and reduced asset values [Source 2].\n"
            "- Refinancing risk: The company faces the risk of being unable to refinance long-term debt. This could impact its financial stability [Source 2].\n\n"
            "No probability or quantified loss estimate is provided for any of these risks [Source 2]."
        )
        claim_verifier = ClaimVerifier()
        verification = claim_verifier.verify(multi_sentence_response, evidence)
        assert verification.overall_status == ClaimOverallStatus.VERIFIED
        assert verification.claims_checked == 6
        assert verification.supported_claims == 6
        assert verification.unsupported_claims == 0
        assert all(c.citation_valid for c in verification.claims)
        assert all(c.status == ClaimStatus.SUPPORTED for c in verification.claims)

    @pytest.mark.asyncio
    async def test_rag_pipeline_prompt_bounds_source_citations(self):
        evidence = _make_northstar_evidence()
        captured_prompt = None

        class MockLLM:
            model_name = "test-model"

            async def generate(self, system_instruction, user_prompt):
                nonlocal captured_prompt
                captured_prompt = user_prompt
                return MagicMock(
                    answer="Supported risk [Source 1].",
                    model_name="test-model",
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    estimated_cost_usd=0.0,
                )

        mock_retrieval = MagicMock()
        mock_diagnostics = RetrievalDiagnostics(
            selected_strategy=RetrievalStrategy.HYBRID,
            selection_reason="Test hybrid",
            query_analysis={"query_type": "conceptual"},
            keyword_result_count=1,
            semantic_result_count=1,
            fusion_result_count=1,
            retrieved_chunks_count=1,
            retrieval_time_ms=1.0,
        )
        mock_retrieval.retrieve = AsyncMock(
            return_value=MagicMock(
                retrieved_chunks=[evidence[1]],
                diagnostics=mock_diagnostics,
            )
        )
        mock_page_selector = MagicMock()
        mock_page_selector.refine = AsyncMock(return_value=[evidence[1]])
        from app.services.confidence_service import ConfidenceService

        pipeline = RagPipeline(
            retrieval_service=mock_retrieval,
            llm_service=MockLLM(),
            evidence_verifier=EvidenceVerifier(),
            confidence_service=ConfidenceService(),
            page_selector=mock_page_selector,
        )
        pipeline._allowed_document_ids = AsyncMock(
            return_value=[evidence[1].document_id]
        )
        mock_db = AsyncMock()
        await pipeline.answer(
            mock_db,
            user_id=evidence[1].user_id,
            question="Identify the major financial and operational risks mentioned in the Northstar Components FY2025 report.",
            document_ids=[evidence[1].document_id],
        )
        assert captured_prompt is not None
        assert "Available source citations are: [Source 1]" in captured_prompt
        assert (
            "Do NOT use document section numbers (such as section 6) as source citations."
            in captured_prompt
        )

    def test_valid_but_wrong_source_number_fails_grounding(self):
        evidence = _make_northstar_evidence()
        # evidence[0] has no risks; evidence[1] has risks
        cv = ClaimVerifier()
        # Citing Source 1 (in-range 1..2, but wrong chunk without risks)
        claim = "Raw-material price volatility: potential operating risk [Source 1]."
        assessment = cv._assess_claim(claim, evidence)
        assert assessment.status == ClaimStatus.UNSUPPORTED
        assert assessment.citation_valid is True
        assert "not supported" in assessment.reason.lower()

    def test_regrounding_identifies_actual_supporting_passage(self):
        evidence = _make_northstar_evidence()
        cv = ClaimVerifier()
        # When cited with wrong Source 1, find_supporting_source locates genuine Source 2
        claim = "Raw-material price volatility: potential operating risk [Source 1]."
        source_idx = cv.find_supporting_source(claim, evidence)
        assert source_idx == 2

    def test_invented_risk_name_rejected_and_not_regrounded(self):
        evidence = _make_northstar_evidence()
        cv = ClaimVerifier()
        fake_risk_1 = "Foreign currency volatility: fluctuating exchange rates impact margins [Source 2]."
        fake_risk_2 = (
            "Cyber security threats: malicious hackers breach networks [Source 2]."
        )

        ass1 = cv._assess_claim(fake_risk_1, evidence)
        ass2 = cv._assess_claim(fake_risk_2, evidence)
        assert ass1.status == ClaimStatus.UNSUPPORTED
        assert ass2.status == ClaimStatus.UNSUPPORTED
        assert cv.find_supporting_source(fake_risk_1, evidence) is None
        assert cv.find_supporting_source(fake_risk_2, evidence) is None

    def test_hallucinated_explanation_rejected_and_not_regrounded(self):
        evidence = _make_northstar_evidence()
        cv = ClaimVerifier()
        # Risk name is real, but explanatory fact/loss is hallucinated
        hallucinated = "Raw-material price volatility: estimated catastrophic loss of $50,000,000 in FY2025 [Source 2]."
        assessment = cv._assess_claim(hallucinated, evidence)
        assert assessment.status == ClaimStatus.UNSUPPORTED
        assert cv.find_supporting_source(hallucinated, evidence) is None

    def test_multiple_citations_grounding(self):
        evidence = _make_northstar_evidence()
        cv = ClaimVerifier()
        # Both Source 1 and Source 2 cited
        claim = (
            "Freight cost increases: potential operating risk [Source 1] [Source 2]."
        )
        assessment = cv._assess_claim(claim, evidence)
        assert assessment.cited_source_numbers == [1, 2]
        assert assessment.status == ClaimStatus.SUPPORTED

    def test_source_order_changes_preserves_strict_chunk_matching(self):
        evidence = _make_northstar_evidence()
        # Invert order: index 0 is chunk with risks, index 1 is chunk without risks
        inverted_evidence = [evidence[1], evidence[0]]
        cv = ClaimVerifier()
        # Now Source 1 has risks, Source 2 does NOT
        claim_src1 = (
            "Raw-material price volatility: potential operating risk [Source 1]."
        )
        claim_src2 = (
            "Raw-material price volatility: potential operating risk [Source 2]."
        )
        assert (
            cv._assess_claim(claim_src1, inverted_evidence).status
            == ClaimStatus.SUPPORTED
        )
        assert (
            cv._assess_claim(claim_src2, inverted_evidence).status
            == ClaimStatus.UNSUPPORTED
        )

    def test_focused_excerpt_centers_on_risk_disclosure(self):
        # In NORTHSTAR_CHUNK_1 (offset 2101), ensure focus excerpt contains the risk text
        claims = [
            "Raw-material price volatility: potential operating risk [Source 1].",
            "Customer concentration: potential operating risk [Source 1].",
        ]
        excerpt = RagPipeline._focus_source_excerpt(
            NORTHSTAR_CHUNK_1, claims, max_chars=600
        )
        assert "Operating risks:" in excerpt
        assert "raw-material price volatility" in excerpt
        assert "customer concentration" in excerpt

    def test_procedural_instructions_filtered_from_terms(self):
        from app.services.evidence_verifier import _terms

        question = (
            "List all financial and operational risks explicitly disclosed in the Northstar Components FY2025 report. "
            "For each risk, distinguish what the document explicitly states from any financial implications you infer. "
            "If the report provides no detailed explanation, say so. Include supporting source citations and do not "
            "present inferred consequences as documented facts."
        )
        terms = _terms(question)
        assert "distinguish" not in terms
        assert "infer" not in terms
        assert "implication" not in terms
        assert "consequence" not in terms
        assert "fact" not in terms
        assert "say" not in terms
        assert "so" not in terms
        assert "present" not in terms
        assert "state" not in terms
        assert "disclose" not in terms
        assert "risk" in terms
        assert "operat" in terms
        assert "northstar" in terms
        assert "component" in terms
        assert "fy2025" in terms

    def test_qualitative_risk_prompt_evidence_verification_sufficient(self):
        evidence = _make_northstar_evidence()
        question = (
            "List all financial and operational risks explicitly disclosed in the Northstar Components FY2025 report. "
            "For each risk, distinguish what the document explicitly states from any financial implications you infer. "
            "If the report provides no detailed explanation, say so. Include supporting source citations and do not "
            "present inferred consequences as documented facts."
        )
        verifier = EvidenceVerifier()
        result = verifier.verify(
            question,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status == EvidenceStatus.SUFFICIENT
        assert result.relevance_score >= 0.70
        assert result.sufficiency_score >= 0.70
        assert "risk" in result.supported_aspects
        assert not result.missing_aspects

    def test_qualitative_risk_disclaimer_and_claims_verified(self):
        evidence = _make_northstar_evidence()
        response_text = (
            "The financial and operational risks explicitly disclosed in the Northstar Components FY2025 report are:\n\n"
            "- Raw-material price volatility: The report identifies this as an operating risk, but provides no probability or quantified loss estimate [Source 2].\n"
            "- Customer concentration: This is listed as an operating risk, with no explanation of the level of concentration or associated loss estimate [Source 2].\n"
            "- Freight cost increases: Cited as an operating risk, with no specified probability or financial impact disclosed [Source 2].\n"
            "- Inventory obsolescence: Listed as an operating risk, with no details on the extent or potential financial consequence [Source 2].\n"
            "- Refinancing risk: Identified as an operating risk, but no probability or loss estimate is provided [Source 2].\n\n"
            "No financial implications are inferred or stated as documented facts; all risk descriptions are limited to identification without quantification or probability [Source 2]."
        )
        claim_verifier = ClaimVerifier()
        verification = claim_verifier.verify(response_text, evidence)
        assert verification.overall_status == ClaimOverallStatus.VERIFIED
        assert verification.claims_checked == 6
        assert verification.supported_claims == 6
        assert verification.unsupported_claims == 0
        assert all(c.citation_valid for c in verification.claims)
        assert all(c.status == ClaimStatus.SUPPORTED for c in verification.claims)

    def test_fabricated_qualitative_risk_unsupported(self):
        evidence = _make_northstar_evidence()
        cv = ClaimVerifier()
        fake_risk = "Foreign currency volatility: fluctuating exchange rates impact operating margins [Source 2]."
        assessment = cv._assess_claim(fake_risk, evidence)
        assert assessment.status == ClaimStatus.UNSUPPORTED
        assert "subject identity is not supported" in assessment.reason.lower()

    def test_unsupported_explanatory_inference_unsupported(self):
        evidence = _make_northstar_evidence()
        cv = ClaimVerifier()
        unsupported_inference = "Raw-material price volatility: caused by disruption in copper mining in South America [Source 2]."
        assessment = cv._assess_claim(unsupported_inference, evidence)
        assert assessment.status == ClaimStatus.UNSUPPORTED
        assert "explanatory assertion is not supported" in assessment.reason.lower()

    def test_absence_of_risk_evidence_fails_verification(self):
        evidence = _make_northstar_evidence()
        # Pass only chunk 0 (income statement & balance sheet, no risk disclosures)
        question = (
            "List all financial and operational risks explicitly disclosed in the Northstar Components FY2025 report. "
            "For each risk, distinguish what the document explicitly states from any financial implications you infer."
        )
        verifier = EvidenceVerifier()
        result = verifier.verify(
            question,
            [evidence[0]],
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status != EvidenceStatus.SUFFICIENT


# ===========================================================================
# Test 17: Ambiguous 'Profit Margin' Clarification Request
# ===========================================================================


class Test17ProfitMarginClarificationFix:
    """Ambiguous profit margin prompts user clarification rather than generic abstention."""

    def test_profit_margin_detected_as_ambiguous(self):
        question = "What was the profit margin?"
        analyzer = QuestionRequirementAnalyzer()
        reqs = analyzer.analyze(question)
        assert reqs.is_ambiguous is True
        assert (
            reqs.ambiguity_reason
            == "'profit margin' does not specify gross profit margin, operating margin, or net profit margin"
        )

    def test_evidence_verifier_notes_clarification_in_missing_aspects(self):
        evidence = _make_northstar_evidence()
        question = "What was the profit margin?"
        verifier = EvidenceVerifier()
        result = verifier.verify(
            question,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        assert result.evidence_status != EvidenceStatus.SUFFICIENT
        assert any(
            "clarification" in aspect.lower() for aspect in result.missing_aspects
        )

    @pytest.mark.asyncio
    async def test_rag_pipeline_returns_clarification_prompt(self):
        evidence = _make_northstar_evidence()
        mock_retrieval = MagicMock()
        mock_diagnostics = RetrievalDiagnostics(
            selected_strategy=RetrievalStrategy.SEMANTIC,
            selection_reason="Test semantic retrieval.",
            query_analysis={"query_type": "general"},
            keyword_result_count=0,
            semantic_result_count=len(evidence),
            fusion_result_count=0,
            retrieved_chunks_count=len(evidence),
            retrieval_time_ms=5.0,
        )
        mock_retrieval.retrieve = AsyncMock(
            return_value=MagicMock(
                retrieved_chunks=evidence,
                diagnostics=mock_diagnostics,
            )
        )
        mock_page_selector = MagicMock()
        mock_page_selector.refine = AsyncMock(return_value=evidence)

        mock_llm = MagicMock()
        mock_llm.model_name = "test-model"

        mock_confidence = MagicMock()
        mock_confidence.assess = MagicMock(
            return_value=ConfidenceAssessment(
                level="low",
                score=0.2,
                factors={},
            )
        )

        pipeline = RagPipeline(
            retrieval_service=mock_retrieval,
            llm_service=mock_llm,
            evidence_verifier=EvidenceVerifier(),
            confidence_service=mock_confidence,
            page_selector=mock_page_selector,
        )
        pipeline._allowed_document_ids = AsyncMock(
            return_value=[evidence[0].document_id]
        )

        mock_db = AsyncMock()
        result = await pipeline.answer(
            mock_db,
            user_id=evidence[0].user_id,
            question="What was the profit margin?",
            document_ids=[evidence[0].document_id],
        )

        assert result.answer != ABSTENTION_ANSWER
        assert "Please clarify your question:" in result.answer
        assert "profit margin" in result.answer
        assert (
            "gross profit margin, operating margin, or net profit margin"
            in result.answer
        )
        assert any(
            "clarification" in aspect.lower()
            for aspect in result.verification.missing_aspects
        )
