"""Explainable relevance, requirement coverage, and evidence sufficiency checks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from enum import Enum
from time import perf_counter
from uuid import UUID

from app.services.question_requirements import (
    QuestionRequirementAnalyzer,
    QuestionRequirements,
)
from app.services.vector_store import VectorSearchResult

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\w)-?\d[\d,]*(?:\.\d+)?\s*%?")
_UNIT = re.compile(
    r"[$€£₹¥]|\b(?:usd|eur|gbp|inr|million|billion|crore|lakh|mn|bn|percent|percentage)\b|%",
    re.IGNORECASE,
)
_CURRENCY_UNIT = re.compile(r"[$€£₹¥]|\b(?:usd|eur|gbp|inr|yen)\b", re.IGNORECASE)
_SCALE_UNIT = re.compile(
    r"\b(?:thousand|million|billion|crore|lakh|mn|bn)\b|%|\bpercent(?:age)?\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "about",
    "all",
    "also",
    "an",
    "and",
    "answer",
    "any",
    "are",
    "as",
    "at",
    "based",
    "be",
    "brief",
    "briefly",
    "by",
    "citation",
    "citations",
    "cite",
    "company",
    "consequence",
    "consequences",
    "contain",
    "containing",
    "describe",
    "described",
    "detail",
    "detailed",
    "details",
    "did",
    "disclose",
    "disclosed",
    "discloses",
    "disclosing",
    "disclosure",
    "disclosures",
    "distinguish",
    "distinguished",
    "distinguishes",
    "distinguishing",
    "do",
    "does",
    "document",
    "documented",
    "documentation",
    "each",
    "enumerate",
    "enumeration",
    "evidence",
    "explain",
    "explanation",
    "explanations",
    "explicit",
    "explicitly",
    "fact",
    "facts",
    "factual",
    "figure",
    "financial",
    "find",
    "for",
    "from",
    "give",
    "given",
    "how",
    "identify",
    "if",
    "implication",
    "implications",
    "in",
    "include",
    "including",
    "infer",
    "inferred",
    "inferring",
    "infers",
    "inference",
    "inferences",
    "into",
    "is",
    "it",
    "its",
    "key",
    "list",
    "listed",
    "listing",
    "main",
    "major",
    "mention",
    "mentioned",
    "name",
    "names",
    "no",
    "not",
    "of",
    "omit",
    "on",
    "only",
    "or",
    "other",
    "page",
    "please",
    "present",
    "presented",
    "presenting",
    "presents",
    "primary",
    "provide",
    "provided",
    "provides",
    "providing",
    "report",
    "say",
    "saying",
    "says",
    "show",
    "so",
    "source",
    "state",
    "stated",
    "states",
    "stating",
    "statement",
    "statements",
    "such",
    "summarize",
    "support",
    "supporting",
    "tell",
    "than",
    "the",
    "then",
    "this",
    "to",
    "use",
    "using",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
    "yours",
}
_TOPIC_ALIASES = {
    "products": (
        "products",
        "product",
        "manufacturer",
        "manufactures",
        "manufacturing",
    ),
    "business model": (
        "sales model",
        "business model",
        "distribution channel",
        "distributor-focused",
        "distributors",
    ),
    "risk": ("risk", "uncertainty", "exposure", "volatility", "threat"),
    "threat": ("threat", "risk", "uncertainty", "exposure"),
    "uncertainty": ("uncertainty", "risk", "exposure", "threat"),
    "challenge": (
        "challenge",
        "constraint",
        "delay",
        "shortage",
        "difficulty",
        "barrier",
    ),
    "strategy": ("strategy", "plan", "initiative", "priority"),
    "outlook": ("outlook", "forecast", "expect", "prospect"),
    "regulatory": ("regulatory", "regulation", "basel", "ifrs", "gaap", "sec"),
    "compliance": ("compliance", "compliant", "requirement", "regulation"),
}


class EvidenceStatus(str, Enum):
    SUFFICIENT = "sufficient"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"


class VerificationServiceError(RuntimeError):
    """Raised when evidence or claim verification cannot complete safely."""


def _stem(token: str) -> str:
    for suffix in ("ional", "edly", "ing", "ies", "ed", "es", "al", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[: -len(suffix)]
    return token


_STEMMED_STOPWORDS = {_stem(w.lower()) for w in _STOPWORDS} | {
    w.lower() for w in _STOPWORDS
}


def _terms(text: str) -> set[str]:
    return {
        st
        for token in _TOKEN.findall(text)
        if (low := token.lower()) not in _STOPWORDS
        and (st := _stem(low)) not in _STEMMED_STOPWORDS
        and len(token) > 1
    }


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered) for phrase in phrases
    )


def _supports_metric_period(
    text: str,
    aliases: tuple[str, ...],
    period: str | None,
    *,
    requires_number: bool,
    window_chars: int = 500,
) -> bool:
    """Require metric, period, and value to occur in the same local passage window."""

    normalized = " ".join(text.split())
    alias_matches = [
        match
        for alias in aliases
        for match in re.finditer(
            rf"(?<!\w){re.escape(alias)}(?!\w)", normalized, re.IGNORECASE
        )
    ]
    if not alias_matches:
        return False
    period_matches = (
        list(re.finditer(rf"(?<!\d){re.escape(period)}(?!\d)", normalized))
        if period
        else []
    )
    for alias_match in alias_matches:
        starts = [alias_match.start()]
        if period:
            starts = [
                min(alias_match.start(), match.start())
                for match in period_matches
                if abs(alias_match.start() - match.start()) <= window_chars
            ]
        for start in starts:
            end = min(len(normalized), start + window_chars)
            window = normalized[max(0, start - window_chars // 2) : end]
            if not requires_number or any(
                not re.search(
                    r"[x*×/]\s*$",
                    window[max(0, m.start() - 16) : m.start()],
                    re.IGNORECASE,
                )
                for m in _NUMBER.finditer(window)
            ):
                return True
    return False


def _supports_explicit_ratio(text: str, metrics: tuple[str, ...]) -> bool:
    normalized = " ".join(text.lower().split())
    if "debt" in metrics and "equity" in metrics:
        return bool(
            re.search(r"\bdebt\s*(?:-|\s+)?to\s*(?:-|\s+)?equity\b", normalized)
            or re.search(r"\bdebt.{0,60}\bequity.{0,60}\bratio\b", normalized)
            or re.search(r"\bratio.{0,60}\bdebt.{0,60}\bequity\b", normalized)
        )
    return bool(re.search(r"\bratio\b", normalized))


@dataclass(frozen=True, slots=True)
class EvidenceVerification:
    evidence_status: EvidenceStatus
    relevance_score: float
    sufficiency_score: float
    supported_aspects: list[str]
    missing_aspects: list[str]
    reason: str
    source_validity_score: float
    valid_chunk_ids: list[UUID]
    requirements: QuestionRequirements
    verification_time_ms: float

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["evidence_status"] = self.evidence_status.value
        values["valid_chunk_ids"] = [str(value) for value in self.valid_chunk_ids]
        values["requirements"] = self.requirements.as_dict()
        return values


class EvidenceVerifier:
    def __init__(
        self,
        *,
        relevance_threshold: float = 0.45,
        sufficiency_threshold: float = 0.70,
        weak_threshold: float = 0.25,
        requirement_analyzer: QuestionRequirementAnalyzer | None = None,
    ) -> None:
        self.relevance_threshold = relevance_threshold
        self.sufficiency_threshold = sufficiency_threshold
        self.weak_threshold = weak_threshold
        self.requirement_analyzer = (
            requirement_analyzer or QuestionRequirementAnalyzer()
        )

    def verify(
        self,
        question: str,
        evidence: list[VectorSearchResult],
        *,
        user_id: UUID,
        allowed_document_ids: set[UUID],
    ) -> EvidenceVerification:
        started = perf_counter()
        requirements = self.requirement_analyzer.analyze(question)
        valid = [
            item
            for item in evidence
            if item.user_id == user_id
            and item.document_id in allowed_document_ids
            and bool(item.filename.strip())
            and bool(item.chunk_text.strip())
            and bool(item.page_numbers)
            and all(page > 0 for page in item.page_numbers)
        ]
        source_validity = len(valid) / len(evidence) if evidence else 0.0
        if not valid:
            return EvidenceVerification(
                EvidenceStatus.INSUFFICIENT,
                0.0,
                0.0,
                [],
                list(requirements.required_aspects),
                "No valid user-owned passages with document and page metadata were retrieved.",
                source_validity,
                [],
                requirements,
                round((perf_counter() - started) * 1000, 3),
            )

        from app.services.financial_calculation import (
            calculate,
            calculation_kind,
            calculation_period_error,
            cash_flow_summary,
            is_cash_flow_summary,
        )
        from app.services.structured_financial_calculation import table_query

        structured_requested = table_query(question, valid)
        summary_requested = is_cash_flow_summary(question) and not structured_requested
        proof = (
            (
                cash_flow_summary(question, valid)
                if summary_requested
                else calculate(question, valid)
            )
            if source_validity == 1.0
            else None
        )
        if structured_requested and proof and requirements.requires_comparison and not requirements.company_names and len(allowed_document_ids) > 1 and {fact.document_id for fact in proof.inputs} != allowed_document_ids:
            proof = None
        calculation_requested = bool(
            re.search(
                r"calculate|compute|derive|find|divided by|percentage of revenue|using.*figures",
                question,
                re.IGNORECASE,
            )
        )
        if structured_requested or summary_requested or (
            calculation_kind(question) and (proof or calculation_requested)
        ):
            return EvidenceVerification(
                EvidenceStatus.SUFFICIENT if proof else EvidenceStatus.WEAK,
                1.0 if proof else 0.0,
                1.0 if proof else 0.0,
                ["verified calculation inputs"] if proof else [],
                []
                if proof
                else [
                    calculation_period_error(question, valid)
                    or "unambiguous same-document input figures and units"
                ],
                "Calculation inputs independently validated"
                if proof
                else "Required calculation inputs are missing or ambiguous",
                source_validity,
                [item.chunk_id for item in valid],
                requirements,
                round((perf_counter() - started) * 1000, 3),
            )

        from app.services.financial_table_extractor import table_evidence_text

        valid = [replace(item, chunk_text=table_evidence_text(item.chunk_text)) for item in valid]
        question_terms = _terms(question)
        passage_coverages = []
        for item in valid:
            passage_terms = _terms(item.chunk_text)
            passage_coverages.append(
                len(question_terms & passage_terms) / len(question_terms)
                if question_terms
                else 0.0
            )
        ordered_coverages = sorted(passage_coverages, reverse=True)
        passage_union = set().union(*(_terms(item.chunk_text) for item in valid))
        union_coverage = (
            len(question_terms & passage_union) / len(question_terms)
            if question_terms
            else 0.0
        )
        relevance = min(
            1.0,
            max(
                0.7 * ordered_coverages[0]
                + 0.3 * (sum(ordered_coverages[:3]) / min(3, len(ordered_coverages))),
                0.6 * union_coverage + 0.4 * ordered_coverages[0],
            ),
        )
        corpus = "\n".join(item.chunk_text for item in valid)
        supported: list[str] = []
        missing: list[str] = []

        for aspect in requirements.required_aspects:
            aspect_supported = False
            matching_texts = [item.chunk_text for item in valid]
            period = next(
                (value for value in requirements.reporting_periods if value in aspect),
                None,
            )
            metric = next(
                (value for value in requirements.metrics if value in aspect), None
            )
            topic = next(
                (value for value in requirements.conceptual_topics if value in aspect),
                None,
            )
            company = next(
                (value for value in requirements.company_names if value == aspect), None
            )
            if metric:
                aliases = requirements.metric_aliases[metric]
                matching_texts = [
                    text for text in matching_texts if _contains_phrase(text, aliases)
                ]
                aspect_supported = bool(matching_texts)
            if period:
                matching_texts = [
                    text
                    for text in matching_texts
                    if (
                        bool(re.search(rf"(?<!\d){re.escape(period)}(?!\d)", text))
                        if not metric
                        else _supports_metric_period(
                            text,
                            requirements.metric_aliases[metric]
                            if metric
                            else (period,),
                            period,
                            requires_number=requirements.requires_numeric_values,
                        )
                    )
                ]
                aspect_supported = bool(matching_texts)
            if topic:
                aliases = _TOPIC_ALIASES.get(topic, (topic,))
                aspect_supported = any(
                    any(
                        _stem(alias) in _terms(text) or _contains_phrase(text, (alias,))
                        for alias in aliases
                    )
                    for text in matching_texts
                )
            if company:
                aspect_supported = company.lower() in corpus.lower()
            if requirements.requires_numeric_values and (metric or period):
                aspect_supported = aspect_supported and any(
                    _NUMBER.search(text) for text in matching_texts
                )
            if aspect == "question topic":
                aspect_supported = relevance >= self.relevance_threshold
            if aspect == "explicit requested ratio":
                aspect_supported = any(
                    _supports_explicit_ratio(text, requirements.metrics)
                    for text in matching_texts
                )
            (supported if aspect_supported else missing).append(aspect)

        if requirements.is_ambiguous:
            missing.append(f"clarification needed: {requirements.ambiguity_reason}")

        coverage = len(supported) / len(requirements.required_aspects)
        units_clear = not requirements.requires_units or bool(_UNIT.search(corpus))
        if (
            units_clear
            and requirements.requires_units
            and requirements.reporting_periods
        ):
            period_units = []
            for period in requirements.reporting_periods:
                period_text = "\n".join(
                    item.chunk_text for item in valid if period in item.chunk_text
                )
                period_units.append(
                    (
                        {
                            value.lower()
                            for value in _CURRENCY_UNIT.findall(period_text)
                        },
                        {value.lower() for value in _SCALE_UNIT.findall(period_text)},
                    )
                )
            currencies = [values for values, _ in period_units if values]
            scales = [values for _, values in period_units if values]
            currencies_consistent = not currencies or bool(
                set.intersection(*currencies)
            )
            scales_consistent = not scales or bool(set.intersection(*scales))
            units_clear = currencies_consistent and scales_consistent
        if not units_clear:
            missing.append("consistent currency or units")
        sufficiency = min(1.0, coverage * 0.75 + relevance * 0.25)
        if not units_clear:
            sufficiency *= 0.8
        all_covered = not missing
        if (
            all_covered
            and relevance >= self.relevance_threshold
            and sufficiency >= self.sufficiency_threshold
            and source_validity == 1.0
        ):
            status = EvidenceStatus.SUFFICIENT
            reason = (
                "Retrieved passages cover the required metrics, periods, and context."
            )
        elif supported or relevance >= self.weak_threshold:
            status = EvidenceStatus.WEAK
            reason = "Some relevant evidence was found, but required information remains incomplete."
        else:
            status = EvidenceStatus.INSUFFICIENT
            reason = "Retrieved passages do not cover the information required by the question."
        return EvidenceVerification(
            status,
            round(relevance, 6),
            round(sufficiency, 6),
            supported,
            list(dict.fromkeys(missing)),
            reason,
            round(source_validity, 6),
            [item.chunk_id for item in valid],
            requirements,
            round((perf_counter() - started) * 1000, 3),
        )
