"""Validated chat requests, grounded answers, and conversation history."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.chat import ChatRole


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    session_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty")
        return value


class ChatSource(BaseModel):
    document_id: UUID
    filename: str
    page_numbers: list[int]
    excerpt: str
    chunk_id: UUID
    similarity_score: float


class RetrievalDiagnosticsResponse(BaseModel):
    selected_strategy: str
    selection_reason: str
    query_analysis: dict[str, object]
    keyword_result_count: int
    semantic_result_count: int
    fusion_result_count: int
    retrieved_chunks_count: int
    retrieval_time_ms: float


class ClaimAssessmentResponse(BaseModel):
    claim: str
    status: str
    source_chunk_ids: list[UUID]
    cited_source_numbers: list[int]
    citation_valid: bool
    support_score: float
    reason: str


class VerificationDiagnosticsResponse(BaseModel):
    evidence_status: str
    overall_status: str
    relevance_score: float
    sufficiency_score: float
    supported_aspects: list[str]
    missing_aspects: list[str]
    claims_checked: int
    supported_claims: int
    unsupported_claims: int
    partially_supported_claims: int
    supporting_citations: int
    claim_support_ratio: float
    citation_validity_score: float
    retrieval_attempts: int
    revision_attempts: int
    removed_claims: int
    verification_time_ms: float
    claims: list[ClaimAssessmentResponse]
    reason: str


class ConfidenceResponse(BaseModel):
    level: str
    score: float
    factors: dict[str, float]
    calibrated_probability: bool
    explanation: str


class ChatAskResponse(BaseModel):
    session_id: UUID
    answer: str
    sources: list[ChatSource]
    retrieved_chunks_count: int
    model_name: str
    retrieval_time_ms: float
    generation_time_ms: float
    usage: dict[str, int | float | None] = Field(default_factory=dict)
    retrieval: RetrievalDiagnosticsResponse
    verification: VerificationDiagnosticsResponse
    confidence: ConfidenceResponse


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: ChatRole
    message: str
    sources: list[ChatSource] = Field(default_factory=list)
    model_name: str | None = None
    retrieved_chunks_count: int | None = None
    retrieval_time_ms: float | None = None
    generation_time_ms: float | None = None
    retrieval: RetrievalDiagnosticsResponse | None = None
    verification: VerificationDiagnosticsResponse | None = Field(
        default=None, validation_alias="verification_metadata"
    )
    confidence: ConfidenceResponse | None = Field(
        default=None, validation_alias="confidence_metadata"
    )
    created_at: datetime


class ChatSessionSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    message_count: int


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class ChatSessionDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    messages: list[ChatMessageResponse]
