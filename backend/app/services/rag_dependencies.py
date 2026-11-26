"""Cached semantic, keyword, adaptive retrieval, and RAG dependency hooks."""

from functools import lru_cache

from app.config import get_settings
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalSelector,
    AdaptiveRetrievalService,
)
from app.services.claim_verifier import ClaimVerifier
from app.services.confidence_service import ConfidenceService
from app.services.embedding_service import EmbeddingService
from app.services.evidence_verifier import EvidenceVerifier
from app.services.keyword_retrieval import KeywordRetrievalService
from app.services.llm_service import LLMService, create_llm_service
from app.services.rag_pipeline import RagPipeline
from app.services.retrieval_service import SemanticRetrievalService
from app.services.vector_store import ChromaVectorStore


@lru_cache
def get_embedding_service() -> EmbeddingService:
    settings = get_settings()
    return EmbeddingService(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
        query_prefix=settings.embedding_query_prefix,
        expected_dimension=settings.embedding_expected_dimension,
        model_revision=settings.embedding_model_revision,
        local_files_only=settings.embedding_local_files_only,
    )


@lru_cache
def get_vector_store() -> ChromaVectorStore:
    settings = get_settings()
    return ChromaVectorStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
        collection_name=settings.chroma_collection,
    )


@lru_cache
def get_llm_service() -> LLMService:
    return create_llm_service(get_settings())


@lru_cache
def get_retrieval_service() -> SemanticRetrievalService:
    settings = get_settings()
    return SemanticRetrievalService(
        get_embedding_service(),
        get_vector_store(),
        default_top_k=settings.rag_top_k,
        minimum_similarity=settings.rag_min_similarity,
    )


@lru_cache
def get_keyword_retrieval_service() -> KeywordRetrievalService:
    settings = get_settings()
    return KeywordRetrievalService(
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        epsilon=settings.bm25_epsilon,
        max_cached_users=settings.bm25_cache_users,
    )


@lru_cache
def get_adaptive_retrieval_service() -> AdaptiveRetrievalService:
    settings = get_settings()
    return AdaptiveRetrievalService(
        get_keyword_retrieval_service(),
        get_retrieval_service(),
        selector=AdaptiveRetrievalSelector(
            exact_term_threshold=settings.adaptive_exact_term_threshold
        ),
        default_top_k=settings.rag_top_k,
        rrf_constant=settings.rrf_constant,
    )


@lru_cache
def get_rag_pipeline() -> RagPipeline:
    settings = get_settings()
    return RagPipeline(
        get_adaptive_retrieval_service(),
        get_llm_service(),
        source_excerpt_chars=settings.rag_source_excerpt_chars,
        evidence_verifier=EvidenceVerifier(
            relevance_threshold=settings.evidence_relevance_threshold,
            sufficiency_threshold=settings.evidence_sufficiency_threshold,
            weak_threshold=settings.evidence_weak_threshold,
        ),
        claim_verifier=ClaimVerifier(
            support_threshold=settings.claim_support_threshold
        ),
        confidence_service=ConfidenceService(),
        initial_top_k=settings.rag_top_k,
        maximum_top_k=settings.evidence_max_top_k,
        maximum_retrieval_attempts=settings.evidence_max_retrieval_attempts,
        maximum_revision_attempts=settings.answer_max_revision_attempts,
    )
