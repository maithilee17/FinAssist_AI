"""Explainable, non-calibrated evidence confidence scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.claim_verifier import ClaimOverallStatus, ClaimVerification
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerification


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    level: str
    score: float
    factors: dict[str, float]
    calibrated_probability: bool = False
    explanation: str = "A deterministic evidence-quality score with safety caps for weak evidence or unsupported claims; not a calibrated probability of factual truth."

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ConfidenceService:
    def assess(
        self,
        evidence: EvidenceVerification,
        claims: ClaimVerification | None,
    ) -> ConfidenceAssessment:
        claim_support = claims.claim_support_ratio if claims else 0.0
        citation_validity = claims.citation_validity_score if claims else 0.0
        factors = {
            "retrieval_relevance": evidence.relevance_score,
            "evidence_sufficiency": evidence.sufficiency_score,
            "claim_support": claim_support,
            "citation_validity": citation_validity,
        }
        score = (
            0.30 * factors["retrieval_relevance"]
            + 0.35 * factors["evidence_sufficiency"]
            + 0.25 * factors["claim_support"]
            + 0.10 * factors["citation_validity"]
        )
        policy_cap = 1.0
        if evidence.evidence_status != EvidenceStatus.SUFFICIENT or (
            claims and claims.overall_status == ClaimOverallStatus.UNSUPPORTED
        ):
            policy_cap = 0.39
        elif claims and claims.overall_status == ClaimOverallStatus.PARTIALLY_SUPPORTED:
            policy_cap = 0.59
        factors["verification_policy_cap"] = policy_cap
        score = min(score, policy_cap)
        level = "high" if score >= 0.8 else "medium" if score >= 0.6 else "low"
        return ConfidenceAssessment(level, round(score, 6), factors)
