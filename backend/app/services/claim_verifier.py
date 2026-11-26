"""Deterministic factual-claim extraction and claim-to-chunk validation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
from time import perf_counter
from uuid import UUID

from app.services.evidence_verifier import _terms
from app.services.financial_table_extractor import table_evidence_text
from app.services.question_requirements import QuestionRequirementAnalyzer
from app.services.vector_store import VectorSearchResult

_CITATION = re.compile(r"\[Source\s+(\d+)\]", re.IGNORECASE)
_CITATION_ONLY = re.compile(r"^(?:\[Source\s+\d+\]\s*)+$", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_BULLET_START = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_ITEM_SPLIT = re.compile(r"\n+(?=\s*(?:[-*•]|\d+[.)])\s+)|\n\s*\n")
_NUMBER = re.compile(r"(?<![A-Za-z])[-(]?\d[\d,]*(?:\.\d+)?\)?\s*%?")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DISCLAIMER_PATTERNS = re.compile(
    r"\b(?:no|without)\s+(?:financial\s+)?implications\b|"
    r"\b(?:not|no)\s+(?:present(?:ed)?|stated|treated)\s+as\s+documented\s+facts?\b|"
    r"\b(?:no|without)\s+(?:probability|quantified\s+loss|quantification|detailed\s+explanation|further\s+details?)\b|"
    r"\b(?:limited\s+to\s+identification|identifi(?:ed|cation)\s+without\s+quantification)\b|"
    r"\b(?:no\s+details?\s+(?:are|is)?\s*provided|not\s+provided\s+in\s+the\s+report)\b|"
    r"\b(?:analytical\s+inferences?|inferred\s+(?:implications?|consequences?))\b",
    re.IGNORECASE,
)
_ABSTENTION_PHRASES = (
    "insufficient information",
    "insufficient evidence",
    "could not find",
    "not found in the uploaded documents",
)
_GENERIC_SCAFFOLDING = {
    "northstar",
    "components",
    "fictional",
    "illustrative",
    "demonstration",
    "report",
    "reports",
    "reported",
    "reporting",
    "identifies",
    "identified",
    "identifying",
    "identify",
    "states",
    "stated",
    "stating",
    "state",
    "notes",
    "noted",
    "noting",
    "note",
    "describes",
    "described",
    "describing",
    "describe",
    "presents",
    "presented",
    "presenting",
    "present",
    "mentions",
    "mentioned",
    "mentioning",
    "mention",
    "discloses",
    "disclosed",
    "disclosing",
    "disclose",
    "commentary",
    "management",
    "company",
    "potential",
    "operational",
    "financial",
    "risk",
    "risks",
    "factor",
    "factors",
    "challenge",
    "challenges",
    "item",
    "items",
    "section",
    "sections",
    "category",
    "categories",
    "facing",
    "faces",
    "posed",
    "poses",
    "could",
    "would",
    "may",
    "might",
    "also",
    "well",
    "such",
    "impact",
    "impacts",
    "impacting",
    "affect",
    "affects",
    "affecting",
}


def _normalize_number(value: str) -> str:
    cleaned = value.replace(",", "").replace("(", "-").replace(")", "").replace(" ", "")
    try:
        return format(Decimal(cleaned.rstrip("%")).normalize(), "f") + (
            "%" if cleaned.endswith("%") else ""
        )
    except InvalidOperation:
        return cleaned


class ClaimStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"


class ClaimOverallStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    claim: str
    status: ClaimStatus
    source_chunk_ids: list[UUID]
    cited_source_numbers: list[int]
    citation_valid: bool
    support_score: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["status"] = self.status.value
        values["source_chunk_ids"] = [str(value) for value in self.source_chunk_ids]
        return values


@dataclass(frozen=True, slots=True)
class ClaimVerification:
    claims: list[ClaimAssessment]
    overall_status: ClaimOverallStatus
    claims_checked: int
    supported_claims: int
    unsupported_claims: int
    partially_supported_claims: int
    claim_support_ratio: float
    citation_validity_score: float
    verification_time_ms: float

    def as_dict(self) -> dict[str, object]:
        return {
            "claims": [claim.as_dict() for claim in self.claims],
            "overall_status": self.overall_status.value,
            "claims_checked": self.claims_checked,
            "supported_claims": self.supported_claims,
            "unsupported_claims": self.unsupported_claims,
            "partially_supported_claims": self.partially_supported_claims,
            "claim_support_ratio": self.claim_support_ratio,
            "citation_validity_score": self.citation_validity_score,
            "verification_time_ms": self.verification_time_ms,
        }


class ClaimVerifier:
    def __init__(self, *, support_threshold: float = 0.35) -> None:
        self.support_threshold = support_threshold
        self.requirements = QuestionRequirementAnalyzer()

    @staticmethod
    def extract_claims(answer: str) -> list[str]:
        raw_claims = []
        pending_prefix = ""
        items = [i.strip() for i in _ITEM_SPLIT.split(answer.strip()) if i.strip()]

        for item in items:
            if item.endswith(":") and not _CITATION.search(item):
                if len(item.split()) <= 2:
                    pending_prefix = f"{pending_prefix} {item}".strip() + " "
                continue

            clean_item = _BULLET_START.sub("", item).strip()
            item_with_prefix = f"{pending_prefix}{clean_item}".strip()
            pending_prefix = ""

            sentence_parts = [
                s.strip(" \t-*•")
                for s in _SENTENCE.split(item_with_prefix)
                if s.strip(" \t-*•")
            ]
            merged = []
            for s in sentence_parts:
                if _CITATION_ONLY.fullmatch(s) and merged:
                    merged[-1] = f"{merged[-1]} {s}"
                else:
                    merged.append(s)

            item_claims = []
            pending_s = []
            for s in merged:
                if len(s.split()) < 3:
                    continue
                lowered = s.lower()
                if any(phrase in lowered for phrase in _ABSTENTION_PHRASES):
                    continue
                if _CITATION.search(s):
                    if pending_s:
                        item_claims.append(" ".join(pending_s + [s]))
                        pending_s = []
                    else:
                        item_claims.append(s)
                else:
                    pending_s.append(s)

            item_claims.extend(pending_s)

            raw_claims.extend(item_claims)

        if pending_prefix:
            raw_claims.append(pending_prefix.strip())

        return raw_claims

    def _assess_claim(
        self, claim: str, evidence: list[VectorSearchResult]
    ) -> ClaimAssessment:
        evidence = [replace(item, chunk_text=table_evidence_text(item.chunk_text)) for item in evidence]
        citations = [int(value) for value in _CITATION.findall(claim)]
        citation_valid = bool(citations) and all(
            1 <= value <= len(evidence) for value in citations
        )
        candidates = (
            [evidence[index - 1] for index in citations if 1 <= index <= len(evidence)]
            if citations
            else evidence
        )
        plain_claim = _CITATION.sub("", claim).strip()
        combined = "\n".join(item.chunk_text for item in candidates)
        claim_years = set(_YEAR.findall(plain_claim))
        evidence_years = set(_YEAR.findall(combined))
        all_doc_years = set().union(
            *(set(_YEAR.findall(item.chunk_text)) for item in evidence)
        )
        claim_numbers = {
            _normalize_number(value) for value in _NUMBER.findall(plain_claim)
        } - claim_years
        evidence_numbers = {
            _normalize_number(value) for value in _NUMBER.findall(combined)
        } - evidence_years
        claim_requirements = self.requirements.analyze(plain_claim)
        metric_supported = all(
            any(alias.lower() in combined.lower() for alias in aliases)
            for aliases in claim_requirements.metric_aliases.values()
        )
        claim_terms = _terms(plain_claim)
        evidence_terms = _terms(combined)
        lexical = (
            len(claim_terms & evidence_terms) / len(claim_terms) if claim_terms else 0.0
        )
        numbers_supported = claim_numbers <= evidence_numbers
        years_supported = claim_years <= evidence_years or (
            bool(candidates) and claim_years <= all_doc_years
        )
        has_hard_facts = bool(
            claim_numbers or claim_years or claim_requirements.metrics
        )
        hard_facts_supported = (
            has_hard_facts
            and numbers_supported
            and years_supported
            and metric_supported
        )
        hard_fact_mismatch = (
            (bool(claim_numbers) and not numbers_supported)
            or (bool(claim_years) and not years_supported)
            or (bool(claim_requirements.metrics) and not metric_supported)
        )

        is_disclaimer = bool(_DISCLAIMER_PATTERNS.search(plain_claim))
        parts = re.split(r"\s*:\s*|\s+[-–—]\s+", plain_claim)

        predicate_supported = True
        if len(parts) >= 2:
            if len(parts[0].split()) > 5 and any(
                w in parts[0].lower()
                for w in (
                    "risk",
                    "mention",
                    "report",
                    "following",
                    "identif",
                    "disclos",
                )
            ):
                subject = parts[1]
                predicate = " ".join(parts[2:]) if len(parts) > 2 else ""
            else:
                subject = parts[0]
                predicate = " ".join(parts[1:])

            subject_terms = _terms(subject) - _GENERIC_SCAFFOLDING
            content_terms = claim_terms - _GENERIC_SCAFFOLDING

            matched_subject = subject_terms & evidence_terms
            subject_supported = (
                (len(matched_subject) / len(subject_terms) >= 0.5)
                if subject_terms
                else True
            )

            # Check predicate if it's substantive and not an absence disclaimer
            pred_terms = _terms(predicate) - _GENERIC_SCAFFOLDING
            if pred_terms and not _DISCLAIMER_PATTERNS.search(predicate):
                all_evidence_terms = set().union(
                    *(set(_terms(item.chunk_text)) for item in evidence)
                )
                matched_pred = pred_terms & (evidence_terms | all_evidence_terms)
                predicate_supported = len(matched_pred) / len(pred_terms) >= 0.20
        else:
            if is_disclaimer:
                has_topic = bool(
                    {
                        "risk",
                        "operat",
                        "probability",
                        "loss",
                        "estimate",
                        "limitation",
                    }
                    & evidence_terms
                )
                subject_supported = has_topic
                content_terms = claim_terms - _GENERIC_SCAFFOLDING
            else:
                subject = plain_claim
                subject_terms = _terms(subject) - _GENERIC_SCAFFOLDING
                content_terms = claim_terms - _GENERIC_SCAFFOLDING
                matched_subject = subject_terms & evidence_terms
                subject_supported = (
                    (len(matched_subject) / len(subject_terms) >= 0.5)
                    if subject_terms
                    else True
                )

        content_lexical = (
            len(content_terms & evidence_terms) / len(content_terms)
            if content_terms
            else lexical
        )

        score = 0.5 * lexical + 0.5 * content_lexical if content_terms else lexical
        if is_disclaimer and subject_supported:
            score = max(score, 0.75)
        if claim_numbers:
            score = 0.55 * float(numbers_supported) + 0.45 * score
        if claim_years:
            score = 0.25 * float(years_supported) + 0.75 * score
        if claim_requirements.metrics:
            score = 0.25 * float(metric_supported) + 0.75 * score

        if (
            hard_fact_mismatch
            or not citation_valid
            or not subject_supported
            or not predicate_supported
        ):
            status = ClaimStatus.UNSUPPORTED
            if hard_fact_mismatch or not citation_valid:
                reason = "A required value, period, metric, or citation conflicts with the retrieved evidence."
            elif not subject_supported:
                reason = "The specific risk or subject identity is not supported by the cited evidence chunk."
            else:
                reason = "The explanatory assertion is not supported by the cited evidence chunk."
        elif (
            citation_valid
            and candidates
            and (hard_facts_supported or not has_hard_facts)
            and score >= self.support_threshold
        ):
            status = ClaimStatus.SUPPORTED
            reason = "The claim's metrics, periods, values, and wording are supported by retrieved evidence."
        elif candidates and (
            score >= self.support_threshold or (has_hard_facts and hard_facts_supported)
        ):
            status = ClaimStatus.PARTIALLY_SUPPORTED
            reason = "Related evidence exists, but one or more claim details or citations are not fully supported."
        else:
            status = ClaimStatus.UNSUPPORTED
            reason = "The claim could not be matched to the required values, periods, metrics, and valid citations."
        supporting_ids = [
            item.chunk_id
            for item in candidates
            if _terms(item.chunk_text) & claim_terms
            and (
                not claim_numbers
                or claim_numbers
                & {_normalize_number(v) for v in _NUMBER.findall(item.chunk_text)}
            )
            and (
                not claim_years
                or claim_years & set(_YEAR.findall(item.chunk_text))
                or claim_years <= all_doc_years
            )
        ]
        if status != ClaimStatus.SUPPORTED:
            supporting_ids = []
        return ClaimAssessment(
            claim=claim,
            status=status,
            source_chunk_ids=list(dict.fromkeys(supporting_ids)),
            cited_source_numbers=citations,
            citation_valid=citation_valid,
            support_score=round(min(1.0, score), 6),
            reason=reason,
        )

    def verify(
        self,
        answer: str,
        evidence: list[VectorSearchResult],
        question: str | None = None,
    ) -> ClaimVerification:
        started = perf_counter()
        from app.services.financial_calculation import (
            calculate,
            calculation_kind,
            cash_flow_summary,
        )

        if answer.startswith(("Verified cash flow summary", "Verified table ")):
            proof = (calculate(question, evidence) if question else None) if answer.startswith("Verified table ") else cash_flow_summary(question or answer, evidence)
            verified = bool(proof and answer == proof.answer)
            claim = ClaimAssessment(
                answer,
                ClaimStatus.SUPPORTED if verified else ClaimStatus.UNSUPPORTED,
                [evidence[i - 1].chunk_id for i in proof.sources] if verified else [],
                list(proof.sources) if verified else [],
                verified,
                float(verified),
                "All financial inputs and Decimal arithmetic independently recomputed"
                if verified
                else "Cash-flow summary does not match supported inputs, scope and citations",
            )
            return ClaimVerification(
                [claim],
                ClaimOverallStatus.VERIFIED
                if verified
                else ClaimOverallStatus.UNSUPPORTED,
                1,
                int(verified),
                int(not verified),
                0,
                float(verified),
                float(verified),
                round((perf_counter() - started) * 1000, 3),
            )
        proof = calculate(answer, evidence)
        if answer.startswith("Derived "):
            # Calculator output must match a fresh reconstruction exactly.
            # Never send altered operands/operators/citations to lexical fact
            # matching, where individually present numbers could look valid.
            verified = bool(proof and not proof.discrepancy and answer == proof.answer)
            reason = (
                "Decimal arithmetic recomputed from cited labelled input figures"
                if verified
                else "Calculation does not match independently recomputed inputs and citations"
            )
            if verified and question:
                expected_kind = calculation_kind(question)
                actual_kind = calculation_kind(answer)
                if expected_kind and actual_kind and expected_kind != actual_kind:
                    verified = False
                    reason = f"Calculation ({actual_kind}) is nonresponsive to requested calculation ({expected_kind})"

            claim = ClaimAssessment(
                answer,
                ClaimStatus.SUPPORTED if verified else ClaimStatus.UNSUPPORTED,
                [evidence[i - 1].chunk_id for i in proof.sources] if verified else [],
                list(proof.sources) if verified else [],
                verified,
                1.0 if verified else 0.0,
                reason,
            )
            return ClaimVerification(
                [claim],
                ClaimOverallStatus.VERIFIED
                if verified
                else ClaimOverallStatus.UNSUPPORTED,
                1,
                int(verified),
                int(not verified),
                0,
                float(verified),
                float(verified),
                round((perf_counter() - started) * 1000, 3),
            )
        if answer.startswith("Discrepancy in "):
            sources = proof.sources if proof else ()
            claim = ClaimAssessment(
                answer,
                ClaimStatus.UNSUPPORTED,
                [evidence[i - 1].chunk_id for i in sources],
                list(sources),
                True,
                0.0,
                "Reported figures conflict; reconciliation discrepancy identified",
            )
            return ClaimVerification(
                [claim],
                ClaimOverallStatus.UNSUPPORTED,
                1,
                0,
                1,
                0,
                0.0,
                1.0,
                round((perf_counter() - started) * 1000, 3),
            )
        extracted = self.extract_claims(answer)
        claims = [self._assess_claim(claim, evidence) for claim in extracted]
        supported = sum(claim.status == ClaimStatus.SUPPORTED for claim in claims)
        partial = sum(
            claim.status == ClaimStatus.PARTIALLY_SUPPORTED for claim in claims
        )
        unsupported = sum(claim.status == ClaimStatus.UNSUPPORTED for claim in claims)
        if claims and supported == len(claims):
            overall = ClaimOverallStatus.VERIFIED
        elif supported or partial:
            overall = ClaimOverallStatus.PARTIALLY_SUPPORTED
        else:
            overall = ClaimOverallStatus.UNSUPPORTED
        support_ratio = supported / len(claims) if claims else 0.0
        citation_validity = (
            sum(claim.citation_valid for claim in claims) / len(claims)
            if claims
            else 0.0
        )
        return ClaimVerification(
            claims=claims,
            overall_status=overall,
            claims_checked=len(claims),
            supported_claims=supported,
            unsupported_claims=unsupported,
            partially_supported_claims=partial,
            claim_support_ratio=round(support_ratio, 6),
            citation_validity_score=round(citation_validity, 6),
            verification_time_ms=round((perf_counter() - started) * 1000, 3),
        )

    def find_supporting_source(
        self, claim: str, evidence: list[VectorSearchResult]
    ) -> int | None:
        """Find an evidence chunk index (1-based) that genuinely supports this claim.

        Only returns an index if the candidate chunk validates all hard facts,
        subject identity, and substantive content terms.
        """
        for index in range(1, len(evidence) + 1):
            test_claim = _CITATION.sub("", claim).strip() + f" [Source {index}]"
            assessment = self._assess_claim(test_claim, evidence)
            if assessment.status == ClaimStatus.SUPPORTED:
                return index
        return None

    @staticmethod
    def retain_supported_claims(verification: ClaimVerification) -> str:
        return " ".join(
            claim.claim
            for claim in verification.claims
            if claim.status == ClaimStatus.SUPPORTED
        ).strip()
