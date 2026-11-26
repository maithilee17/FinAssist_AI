"""Transparent rule-based analysis of financial retrieval queries."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum


class QueryType(str, Enum):
    EXACT_FACT = "exact_fact"
    FINANCIAL_METRIC = "financial_metric"
    COMPARISON = "comparison"
    CONCEPTUAL = "conceptual"
    REGULATORY = "regulatory"
    DESCRIPTIVE = "descriptive"
    GENERAL = "general"
    CALCULATION = "calculation"


_FINANCIAL_YEAR = re.compile(
    r"\b(?:fy\s*[-']?\s*)?(?:19|20)\d{2}(?:\s*[-/]\s*\d{2,4})?\b", re.IGNORECASE
)
_NUMERIC_REFERENCE = re.compile(
    r"(?:[$€£₹¥]\s*)?\(?-?\d[\d,]*(?:\.\d+)?\)?\s*(?:%|million|billion|crore|lakh|mn|bn)?",
    re.IGNORECASE,
)
_COMPANY_NAME = re.compile(
    r"\b(?:[A-Z][A-Za-z&.-]+\s+){0,4}(?:Inc|Corp|Corporation|Ltd|Limited|LLC|PLC|Bank|Holdings)\b"
)
_QUOTED_TERM = re.compile(r"[\"']([^\"']{2,80})[\"']")

FINANCIAL_TERMS = {
    "inventory",
    "revenue",
    "sales",
    "profit",
    "gross profit",
    "net profit",
    "net income",
    "operating income",
    "operating profit",
    "income",
    "earnings",
    "ebit",
    "ebitda",
    "expenses",
    "assets",
    "total assets",
    "current assets",
    "liabilities",
    "total liabilities",
    "current liabilities",
    "equity",
    "cash flow",
    "ending cash",
    "beginning cash",
    "net cash increase",
    "net change in cash",
    "margin",
    "dividend",
    "debt",
    "capital",
    "eps",
    "roe",
    "roa",
    "unit case volume",
}


def extract_financial_years(text: str) -> tuple[str, ...]:
    years: list[str] = []
    for match in _FINANCIAL_YEAR.finditer(text):
        digits = re.findall(r"(?:19|20)\d{2}", match.group(0))
        years.extend(digits)
    return tuple(dict.fromkeys(years))


def extract_financial_metrics(text: str) -> tuple[str, ...]:
    lowered = " ".join(text.lower().split())
    metrics = [term for term in FINANCIAL_TERMS if _contains_any(lowered, {term})]
    if re.search(r"\bsales\s+(?:model|channels?|strategy|approach)\b", lowered):
        metrics = [term for term in metrics if term != "sales"]
    return tuple(sorted(metrics, key=lambda value: (-len(value), value)))


def extract_company_names(text: str) -> tuple[str, ...]:
    names = [match.group(0) for match in _COMPANY_NAME.finditer(text)]
    # Proper-name subjects need not end in a legal suffix. Require a grammatical
    # entity context and exclude title-cased financial labels, not a company list.
    for match in re.finditer(
        r"\b(?:for|did|does|was|were|of|at|from|about|by)\s+"
        r"([A-Z][A-Za-z&.-]+(?:\s+[A-Z][A-Za-z&.-]+){1,4})\b",
        text,
    ):
        candidate = match.group(1)
        if not set(candidate.lower().split()) & {
            "cash",
            "flow",
            "flows",
            "income",
            "profit",
            "assets",
            "revenue",
            "total",
            "current",
            "financial",
            "fiscal",
            "year",
            "net",
            "operating",
        }:
            names.append(candidate)
    return tuple(dict.fromkeys(names))


def descriptive_business_topics(text: str) -> tuple[str, ...]:
    topics = []
    if re.search(r"\bproducts?|manufactur\w*\b", text, re.IGNORECASE):
        topics.append("products")
    if re.search(
        r"\b(?:sales|business|distribution)\s+(?:model|channels?|approach)\b",
        text,
        re.IGNORECASE,
    ):
        topics.append("business model")
    return tuple(topics)


COMPARISON_TERMS = {
    "compare",
    "comparison",
    "versus",
    "vs",
    "between",
    "change",
    "changed",
    "increase",
    "increased",
    "decrease",
    "decreased",
    "growth",
    "decline",
    "year over year",
    "year-on-year",
    "yoy",
    "difference",
}
REGULATORY_TERMS = {
    "ifrs",
    "gaap",
    "sec",
    "basel",
    "regulatory",
    "regulation",
    "compliance",
    "capital adequacy",
    "filing",
    "disclosure requirement",
}
CONCEPTUAL_TERMS = {
    "why",
    "how",
    "explain",
    "explanation",
    "challenge",
    "risk",
    "threat",
    "uncertainty",
    "strategy",
    "factor",
    "driver",
    "impact",
    "outlook",
    "rationale",
    "opportunity",
}
DESCRIPTIVE_TERMS = {
    "describe",
    "described",
    "description",
    "summarize",
    "summarized",
    "summary",
    "overview",
    "discuss",
    "what happened",
    "list",
    "listed",
    "listing",
    "enumerate",
    "enumerated",
    "enumeration",
    "outline",
    "detail",
}


def _contains_any(text: str, terms: set[str]) -> bool:
    for term in terms:
        phrase_pattern = re.escape(term).replace(r"\ ", r"\s+")
        plural = r"(?:s|es)?" if " " not in term else ""
        if re.search(rf"(?<!\w){phrase_pattern}{plural}(?!\w)", text):
            return True
    return False


@dataclass(frozen=True, slots=True)
class QueryAnalysis:
    query_type: QueryType
    has_financial_year: bool
    has_numeric_reference: bool
    has_currency_reference: bool
    has_comparison: bool
    has_exact_terms: bool
    has_company_name: bool
    has_regulatory_terms: bool
    has_financial_metrics: bool
    requires_semantic_context: bool
    exact_signal_count: int
    financial_years: tuple[str, ...]
    financial_metrics: tuple[str, ...]
    company_names: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["query_type"] = self.query_type.value
        return values


class FinancialQueryAnalyzer:
    def analyze(self, query: str) -> QueryAnalysis:
        query = query.strip()
        lowered = " ".join(query.lower().split())
        years = extract_financial_years(query)
        metrics = extract_financial_metrics(query)
        companies = extract_company_names(query)
        has_year = bool(years)
        has_numeric = bool(_NUMERIC_REFERENCE.search(_FINANCIAL_YEAR.sub(" ", query)))
        has_currency = bool(
            re.search(r"[$€£₹¥]|\b(?:usd|eur|gbp|inr|yen)\b", query, re.IGNORECASE)
        )
        comparison_text = re.sub(
            r"\bnet (?:change|increase|decrease) in cash\b", " ", lowered
        )
        has_comparison = _contains_any(comparison_text, COMPARISON_TERMS)
        has_company = bool(companies)
        has_regulatory = _contains_any(lowered, REGULATORY_TERMS)
        has_metrics = bool(metrics)
        has_conceptual = _contains_any(lowered, CONCEPTUAL_TERMS)
        has_descriptive = _contains_any(lowered, DESCRIPTIVE_TERMS) or bool(
            descriptive_business_topics(query)
        )
        has_quoted = bool(_QUOTED_TERM.search(query))
        exact_signal_count = sum(
            (
                has_year,
                has_numeric,
                has_currency,
                has_company,
                has_regulatory,
                has_metrics,
                has_quoted,
            )
        )
        has_exact = exact_signal_count > 0
        requires_semantic = has_conceptual or has_descriptive

        from app.services.financial_calculation import (
            calculation_kind,
            is_composite_financial_query,
        )

        if (
            not is_composite_financial_query(query)
            and calculation_kind(query)
            and (
                re.search(
                    r"calculate|calculation|compute|derive|divided by|reconcil|formula",
                    lowered,
                )
                or (not has_conceptual and not years)
            )
        ):
            query_type = QueryType.CALCULATION
            requires_semantic = True
        elif has_comparison:
            query_type = QueryType.COMPARISON
        elif has_regulatory:
            query_type = QueryType.REGULATORY
        elif has_conceptual:
            query_type = QueryType.CONCEPTUAL
        elif is_composite_financial_query(query):
            query_type = QueryType.DESCRIPTIVE
        elif has_metrics and (has_year or has_numeric or has_currency):
            query_type = QueryType.FINANCIAL_METRIC
        elif has_descriptive:
            query_type = QueryType.DESCRIPTIVE
        elif has_year or has_numeric or has_company or has_quoted:
            query_type = QueryType.EXACT_FACT
        else:
            query_type = QueryType.GENERAL

        return QueryAnalysis(
            query_type=query_type,
            has_financial_year=has_year,
            has_numeric_reference=has_numeric,
            has_currency_reference=has_currency,
            has_comparison=has_comparison,
            has_exact_terms=has_exact,
            has_company_name=has_company,
            has_regulatory_terms=has_regulatory,
            has_financial_metrics=has_metrics,
            requires_semantic_context=requires_semantic,
            exact_signal_count=exact_signal_count,
            financial_years=years,
            financial_metrics=metrics,
            company_names=companies,
        )
