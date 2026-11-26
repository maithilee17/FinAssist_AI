"""Query-aware page refinement for exact numeric evidence and citations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentPage
from app.services.question_requirements import (
    QuestionRequirementAnalyzer,
    QuestionRequirements,
)
from app.services.vector_store import VectorSearchResult

_NUMBER = re.compile(r"(?<![A-Za-z])[-(]?\d[\d,]*(?:\.\d+)?\)?\s*%?")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_INR_CONTEXT = re.compile(r"Indian\s+rupees\s*\(INR\)", re.IGNORECASE)
_MISSING_RUPEE_GLYPH = re.compile(r"(?<![A-Za-z])I(?=\s*(?:\d[\d,]*(?:\.\d+)?|lakh\b))")
_QUESTION_SCAFFOLD = {
    "about",
    "all",
    "also",
    "answer",
    "any",
    "based",
    "brief",
    "briefly",
    "citation",
    "citations",
    "cite",
    "company",
    "contain",
    "containing",
    "describe",
    "described",
    "detail",
    "detailed",
    "details",
    "disclose",
    "disclosed",
    "disclosure",
    "disclosures",
    "document",
    "each",
    "enumerate",
    "enumeration",
    "evidence",
    "explain",
    "explanation",
    "explanations",
    "explicit",
    "explicitly",
    "figure",
    "financial",
    "find",
    "give",
    "given",
    "identify",
    "include",
    "including",
    "key",
    "list",
    "listed",
    "listing",
    "main",
    "major",
    "mention",
    "primary",
    "name",
    "names",
    "not",
    "omit",
    "only",
    "other",
    "page",
    "provide",
    "provided",
    "report",
    "show",
    "source",
    "state",
    "summarize",
    "support",
    "tell",
    "use",
    "using",
}
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_FINANCIAL_UNIT = re.compile(
    r"[$€£₹¥]|\b(?:inr|usd|eur|gbp|lakh|crore|thousand|million|billion|mn|bn)\b",
    re.IGNORECASE,
)


def _normalized_number_matches(
    text: str, *, allow_percent: bool
) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for match in _NUMBER.finditer(text):
        value = match.group(0).strip()
        if _YEAR.fullmatch(value.strip("() -%")):
            continue
        if not allow_percent and "%" in value:
            continue
        prefix = text[max(0, match.start() - 16) : match.start()]
        suffix = text[match.end() : match.end() + 2]
        if re.search(r"\bpage\s*$", prefix, re.IGNORECASE):
            continue
        if re.search(r"[x*×/]\s*$", prefix, re.IGNORECASE):
            continue
        if suffix.startswith("."):
            continue
        matches.append(match)
    return matches


def _repair_confirmed_inr_glyph(text: str, *, document_uses_inr: bool) -> str:
    """Repair the sample PDF's missing rupee glyph only with explicit INR context."""

    if not document_uses_inr:
        return text
    return _MISSING_RUPEE_GLYPH.sub("₹", text)


@dataclass(frozen=True, slots=True)
class _PageCandidate:
    result: VectorSearchResult
    score: float
    retrieval_rank: int
    has_metric_value: bool


class EvidencePageSelector:
    """Narrow multi-page chunks to a real page for simple numeric fact questions.

    Retrieval still determines which chunks are eligible. This selector only uses
    authenticated ``DocumentPage`` rows represented by those chunks and keeps the
    original chunk UUID, preserving ownership and traceability.
    """

    def __init__(
        self, requirement_analyzer: QuestionRequirementAnalyzer | None = None
    ) -> None:
        self.requirement_analyzer = (
            requirement_analyzer or QuestionRequirementAnalyzer()
        )

    @staticmethod
    def _is_refinable(requirements: QuestionRequirements) -> bool:
        return (
            requirements.requires_numeric_values
            and len(requirements.metrics) == 1
            and not requirements.requires_comparison
        )

    @staticmethod
    def _score_page(
        question: str, text: str, requirements: QuestionRequirements
    ) -> tuple[float, bool]:
        lowered = " ".join(text.lower().split())
        aliases = requirements.metric_aliases[requirements.metrics[0]]
        alias_matches = [
            match
            for alias in aliases
            for match in re.finditer(
                rf"(?<!\w){re.escape(alias.lower())}(?!\w)", lowered
            )
        ]
        if not alias_matches:
            return 0.0, False

        allow_percent = bool(
            re.search(
                r"%|\b(?:percent(?:age)?|margin|ratio|rate)\b", question, re.IGNORECASE
            )
        )
        numbers = _normalized_number_matches(lowered, allow_percent=allow_percent)
        best_proximity = 0.0
        unit_near_metric = False
        for alias_match in alias_matches:
            metric_window = lowered[
                max(0, alias_match.start() - 100) : alias_match.end() + 180
            ]
            unit_near_metric = unit_near_metric or bool(
                _FINANCIAL_UNIT.search(metric_window)
            )
            for number_match in numbers:
                if number_match.start() >= alias_match.end():
                    distance = number_match.start() - alias_match.end()
                    direction_weight = 1.0
                else:
                    distance = alias_match.start() - number_match.end()
                    direction_weight = 0.55
                if distance <= 180:
                    best_proximity = max(
                        best_proximity,
                        direction_weight / (1.0 + distance / 60.0),
                    )

        query_terms = {
            value.lower()
            for value in _WORD.findall(question)
            if value.lower() not in _QUESTION_SCAFFOLD and len(value) > 1
        }
        page_terms = {value.lower() for value in _WORD.findall(text)}
        query_coverage = (
            len(query_terms & page_terms) / len(query_terms) if query_terms else 0.0
        )
        period_coverage = (
            sum(period in text for period in requirements.reporting_periods)
            / len(requirements.reporting_periods)
            if requirements.reporting_periods
            else 1.0
        )
        metric_frequency = min(3, len(alias_matches)) / 3.0
        has_metric_value = best_proximity > 0.0
        score = (
            4.0
            + 3.0 * best_proximity
            + 1.25 * query_coverage
            + 1.0 * period_coverage
            + 0.5 * metric_frequency
            + 1.5 * float(unit_near_metric)
        )
        return score, has_metric_value

    async def refine(
        self,
        db: AsyncSession,
        question: str,
        results: list[VectorSearchResult],
        *,
        user_id: UUID,
        allowed_document_ids: set[UUID],
    ) -> list[VectorSearchResult]:
        from app.services.financial_calculation import calculation_kind

        if calculation_kind(question) or any(x.chunk_text.startswith("[FINASSIST_TABLE_") for x in results):
            return results
        if not results:
            return results
        requirements = self.requirement_analyzer.analyze(question)
        if not self._is_refinable(requirements):
            return results

        represented_pages = {
            (item.document_id, page)
            for item in results
            if item.user_id == user_id and item.document_id in allowed_document_ids
            for page in item.page_numbers
        }
        if not represented_pages:
            return results

        rows = list(
            (
                await db.execute(
                    select(DocumentPage, Document.filename)
                    .join(Document, Document.id == DocumentPage.document_id)
                    .where(
                        Document.user_id == user_id,
                        Document.id.in_(allowed_document_ids),
                    )
                )
            ).all()
        )
        pages = {
            (page.document_id, page.page_number): (page, filename)
            for page, filename in rows
            if (page.document_id, page.page_number) in represented_pages
        }
        if not pages:
            return results

        inr_documents = {
            page.document_id
            for page, _ in rows
            if _INR_CONTEXT.search(page.extracted_text)
        }
        by_page: dict[tuple[UUID, int], _PageCandidate] = {}
        for retrieval_rank, item in enumerate(results):
            if item.user_id != user_id or item.document_id not in allowed_document_ids:
                continue
            for page_number in item.page_numbers:
                page_value = pages.get((item.document_id, page_number))
                if page_value is None:
                    continue
                page, filename = page_value
                score, has_metric_value = self._score_page(
                    question, page.extracted_text, requirements
                )
                if score <= 0.0:
                    continue
                text = _repair_confirmed_inr_glyph(
                    page.extracted_text,
                    document_uses_inr=item.document_id in inr_documents,
                )
                candidate = _PageCandidate(
                    result=VectorSearchResult(
                        chunk_id=item.chunk_id,
                        user_id=item.user_id,
                        document_id=item.document_id,
                        filename=filename,
                        page_numbers=[page_number],
                        chunk_text=text,
                        similarity_score=item.similarity_score,
                        section=item.section,
                    ),
                    score=score,
                    retrieval_rank=retrieval_rank,
                    has_metric_value=has_metric_value,
                )
                key = (item.document_id, page_number)
                existing = by_page.get(key)
                if existing is None or (candidate.score, -candidate.retrieval_rank) > (
                    existing.score,
                    -existing.retrieval_rank,
                ):
                    by_page[key] = candidate

        candidates = sorted(
            by_page.values(),
            key=lambda item: (
                -item.score,
                item.retrieval_rank,
                item.result.page_numbers,
            ),
        )
        with_values = [item for item in candidates if item.has_metric_value]
        if not with_values:
            return results
        # A single-metric value question needs the strongest directly supported
        # page, not unrelated pages that merely mention the same metric.
        return [with_values[0].result]
