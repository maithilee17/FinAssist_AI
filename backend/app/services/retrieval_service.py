"""Semantic retrieval over user-scoped ChromaDB chunks."""

from collections.abc import Sequence
from uuid import UUID

from app.services.embedding_service import EmbeddingService
from app.services.vector_store import ChromaVectorStore, VectorSearchResult


class SemanticRetrievalService:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: ChromaVectorStore,
        *,
        default_top_k: int = 5,
        minimum_similarity: float = 0.25,
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.default_top_k = default_top_k
        self.minimum_similarity = minimum_similarity

    def retrieve(
        self,
        question: str,
        *,
        user_id: UUID,
        document_ids: Sequence[UUID] | None = None,
        top_k: int | None = None,
    ) -> list[VectorSearchResult]:
        query_embedding = self.embedding_service.embed_query(question)
        results = self.vector_store.search_similar_chunks(
            query_embedding,
            user_id=user_id,
            document_ids=document_ids,
            top_k=top_k or self.default_top_k,
        )
        best_by_chunk: dict[UUID, VectorSearchResult] = {}
        for result in results:
            if (
                result.user_id != user_id
                or result.similarity_score < self.minimum_similarity
            ):
                continue
            existing = best_by_chunk.get(result.chunk_id)
            if existing is None or result.similarity_score > existing.similarity_score:
                best_by_chunk[result.chunk_id] = result
        return sorted(
            best_by_chunk.values(), key=lambda item: item.similarity_score, reverse=True
        )
