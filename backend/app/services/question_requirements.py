"""Structured answer requirements derived from the Phase 5 query analyzer."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.services.query_analyzer import (
    FinancialQueryAnalyzer,
    QueryAnalysis,
    QueryType,
    descriptive_business_topics,
)

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "inventory": ("inventory", "inventories"),
    "revenue": ("revenue", "sales", "turnover"),
    "sales": ("sales", "revenue", "turnover"),
    "profit": ("profit", "net profit", "operating profit"),
    "gross profit": ("gross profit",),
    "net profit": ("net profit", "net income"),
    "operating profit": ("operating profit", "operating income"),
    "income": ("income", "net income"),
    "earnings": ("earnings", "net income", "profit"),
    "expenses": ("expenses", "expense", "costs"),
    "assets": ("assets",),
    "total assets": ("total assets", "assets"),
    "current assets": ("current assets",),
    "liabilities": ("liabilities",),
    "total liabilities": ("total liabilities", "liabilities"),
    "current liabilities": ("current liabilities",),
    "cash flow": ("cash flow", "cash flows"),
    "ending cash": ("cash at end of year", "ending cash"),
    "beginning cash": ("cash at beginning of year", "beginning cash"),
    "net cash increase": (
        "net increase in cash",
        "net change in cash",
        "net cash increase",
    ),
    "net change in cash": (
        "net change in cash",
        "net increase in cash",
        "net cash change",
    ),
    "margin": ("margin",),
    "capital": ("capital", "capital adequacy"),
    "unit case volume": ("unit case volume", "unit cases"),
}
_VALUE_QUESTION = re.compile(
    r"\b(?:what was|what were|how much|how many|amount|value|ratio|percentage|rate)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QuestionRequirements:
    query_analysis: QueryAnalysis
    metrics: tuple[str, ...]
    metric_aliases: dict[str, tuple[str, ...]]
    reporting_periods: tuple[str, ...]
    company_names: tuple[str, ...]
    requires_comparison: bool
    requires_numeric_values: bool
    requires_units: bool
    conceptual_topics: tuple[str, ...]
    required_aspects: tuple[str, ...]
    is_ambiguous: bool
    ambiguity_reason: str | None
    requires_explicit_ratio: bool

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["query_analysis"] = self.query_analysis.as_dict()
        return values


class QuestionRequirementAnalyzer:
    def __init__(self, analyzer: FinancialQueryAnalyzer | None = None) -> None:
        self.analyzer = analyzer or FinancialQueryAnalyzer()

    def analyze(self, question: str) -> QuestionRequirements:
        analysis = self.analyzer.analyze(question)
        metrics = analysis.financial_metrics
        aliases = {metric: _METRIC_ALIASES.get(metric, (metric,)) for metric in metrics}
        numeric = bool(metrics) and (
            bool(_VALUE_QUESTION.search(question))
            or analysis.has_comparison
            or (
                bool(analysis.financial_years)
                and analysis.query_type
                not in {QueryType.CONCEPTUAL, QueryType.DESCRIPTIVE}
            )
        )
        topics: list[str] = []
        topics.extend(descriptive_business_topics(question))
        lowered = question.lower()
        for topic in (
            "risk",
            "threat",
            "uncertainty",
            "challenge",
            "strategy",
            "outlook",
            "regulatory",
            "compliance",
        ):
            if topic in lowered or f"{topic}s" in lowered:
                topics.append(topic)
        if analysis.query_type == QueryType.REGULATORY and "regulatory" not in topics:
            topics.append("regulatory")

        bare_profit = "profit" in metrics and not re.search(
            r"\b(?:gross|net|operating|pre-tax|pretax|after-tax)\s+profit\b",
            lowered,
        )
        broad_performance = bool(
            re.search(r"\bperform(?:ed|ance)?\b", lowered)
        ) and not bool(metrics or topics)
        ambiguity_reason = None
        if bare_profit:
            if "margin" in lowered:
                ambiguity_reason = "'profit margin' does not specify gross profit margin, operating margin, or net profit margin"
            else:
                ambiguity_reason = (
                    "'profit' does not specify gross, operating, pre-tax, or net profit"
                )
        elif broad_performance:
            ambiguity_reason = "'performance' does not identify a financial metric"
        requires_explicit_ratio = bool(re.search(r"\bratio\b", lowered))

        aspects: list[str] = []
        if metrics:
            for metric in metrics:
                if analysis.financial_years:
                    aspects.extend(
                        f"{period} {metric}" for period in analysis.financial_years
                    )
                else:
                    aspects.append(metric)
        aspects.extend(topics)
        if not metrics and descriptive_business_topics(question):
            aspects.extend(analysis.financial_years)
        aspects.extend(analysis.company_names)
        if requires_explicit_ratio:
            aspects.append("explicit requested ratio")
        if not aspects:
            aspects.append("question topic")
        return QuestionRequirements(
            query_analysis=analysis,
            metrics=metrics,
            metric_aliases=aliases,
            reporting_periods=analysis.financial_years,
            company_names=analysis.company_names,
            requires_comparison=analysis.has_comparison,
            requires_numeric_values=numeric,
            requires_units=numeric
            and (analysis.has_comparison or len(analysis.financial_years) > 1),
            conceptual_topics=tuple(topics),
            required_aspects=tuple(dict.fromkeys(aspects)),
            is_ambiguous=ambiguity_reason is not None,
            ambiguity_reason=ambiguity_reason,
            requires_explicit_ratio=requires_explicit_ratio,
        )
