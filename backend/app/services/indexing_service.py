"""Generate and persist embeddings for relational document chunks."""

import logging
from collections.abc import Sequence

from app.models.document import Document, DocumentChunk
from app.services.embedding_service import EmbeddingService, EmbeddingServiceError
from app.services.vector_store import ChromaVectorStore, VectorChunk, VectorStoreError

logger = logging.getLogger(__name__)


class DocumentIndexingError(RuntimeError):
    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage


class DocumentIndexingService:
    def __init__(
        self, embedding_service: EmbeddingService, vector_store: ChromaVectorStore
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store

    def index_document(
        self, document: Document, chunks: Sequence[DocumentChunk]
    ) -> int:
        if not chunks:
            raise DocumentIndexingError(
                "No extractable text was found to index.", stage="chunk_validation"
            )
        vector_chunks = [
            VectorChunk(
                id=chunk.id,
                user_id=document.user_id,
                document_id=document.id,
                filename=document.filename,
                text=chunk.text,
                page_numbers=list(chunk.page_numbers),
                chunk_index=chunk.chunk_index,
            )
            for chunk in chunks
        ]
        try:
            embeddings = self.embedding_service.embed_documents(
                [chunk.text for chunk in vector_chunks]
            )
        except EmbeddingServiceError as exc:
            raise DocumentIndexingError(
                f"Embedding step failed ({exc.code}): {exc}", stage="embedding"
            ) from exc
        if len(embeddings) != len(vector_chunks):
            raise DocumentIndexingError(
                "Embedding step returned an unexpected vector count.",
                stage="embedding_validation",
            )
        try:
            self.vector_store.delete_document_chunks(document.user_id, document.id)
            stored = self.vector_store.add_chunks(vector_chunks, embeddings)
            verified = self.vector_store.count_document_chunks(
                document.user_id, document.id
            )
        except VectorStoreError as exc:
            try:
                self.vector_store.delete_document_chunks(document.user_id, document.id)
            except VectorStoreError:
                logger.exception(
                    "Partial vector cleanup failed document=%s user=%s",
                    document.id,
                    document.user_id,
                )
            raise DocumentIndexingError(
                "The vector store could not complete document indexing; any partial "
                "vectors were scheduled for cleanup.",
                stage="vector_store",
            ) from exc
        if stored != len(chunks) or verified != len(chunks):
            try:
                self.vector_store.delete_document_chunks(document.user_id, document.id)
            except VectorStoreError:
                logger.exception(
                    "Verification cleanup failed document=%s user=%s",
                    document.id,
                    document.user_id,
                )
            raise DocumentIndexingError(
                "Indexed chunk verification failed: "
                f"expected {len(chunks)}, found {verified}.",
                stage="vector_verification",
            )
        return verified
