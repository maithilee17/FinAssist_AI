"""Deterministic tests for transparent financial query analysis."""

from app.services.query_analyzer import FinancialQueryAnalyzer, QueryType


def test_exact_financial_question_detects_year_metric_and_currency() -> None:
    analysis = FinancialQueryAnalyzer().analyze(
        "What was Acme Corp revenue of $1.2 billion in FY2025?"
    )
    assert analysis.query_type == QueryType.FINANCIAL_METRIC
    assert analysis.has_financial_year
    assert analysis.has_financial_metrics
    assert analysis.has_currency_reference
    assert analysis.has_numeric_reference
    assert analysis.has_company_name


def test_comparison_question_is_prioritized() -> None:
    analysis = FinancialQueryAnalyzer().analyze(
        "How did revenue change between FY2024 and FY2025?"
    )
    assert analysis.query_type == QueryType.COMPARISON
    assert analysis.has_comparison
    assert analysis.requires_semantic_context


def test_conceptual_question_requires_semantic_context() -> None:
    analysis = FinancialQueryAnalyzer().analyze(
        "What challenges did the company face while expanding overseas?"
    )
    assert analysis.query_type == QueryType.CONCEPTUAL
    assert analysis.requires_semantic_context
    assert not analysis.has_financial_year


def test_regulatory_question_detects_exact_regulatory_term() -> None:
    analysis = FinancialQueryAnalyzer().analyze(
        "Which Basel III capital adequacy requirement is disclosed?"
    )
    assert analysis.query_type == QueryType.REGULATORY
    assert analysis.has_regulatory_terms
    assert analysis.has_exact_terms


def test_short_regulatory_terms_do_not_match_inside_other_words() -> None:
    analysis = FinancialQueryAnalyzer().analyze("Summarize this section of the report")
    assert analysis.query_type == QueryType.DESCRIPTIVE
    assert not analysis.has_regulatory_terms


def test_plural_financial_metric_is_detected() -> None:
    analysis = FinancialQueryAnalyzer().analyze(
        "What risks could affect gross margins?"
    )
    assert "margin" in analysis.financial_metrics
    assert analysis.requires_semantic_context


def test_unit_case_volume_is_a_financial_metric() -> None:
    analysis = FinancialQueryAnalyzer().analyze(
        "How did unit case volume change from 2023 to 2024?"
    )
    assert "unit case volume" in analysis.financial_metrics
    assert analysis.has_comparison
