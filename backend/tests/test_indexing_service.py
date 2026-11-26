"""Regression checks for clear, safe document-indexing failures."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.embedding_service import EmbeddingServiceError
from app.services.indexing_service import DocumentIndexingError, DocumentIndexingService
from app.services.vector_store import VectorStoreError


class Embeddings:
    model_name = "test-model"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class UnavailableVectorStore:
    delete_calls = 0

    def delete_document_chunks(self, user_id, document_id) -> None:
        del user_id, document_id
        self.delete_calls += 1
        raise VectorStoreError("Document vectors could not be deleted")


def test_vector_store_failure_has_indexing_context() -> None:
    document = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), filename="annual-report.pdf"
    )
    chunk = SimpleNamespace(
        id=uuid4(),
        text="Revenue was $1 million.",
        page_numbers=[7],
        chunk_index=0,
    )

    with pytest.raises(DocumentIndexingError) as error:
        DocumentIndexingService(Embeddings(), UnavailableVectorStore()).index_document(
            document, [chunk]
        )

    assert "vector store could not complete" in str(error.value).lower()
    assert "indexing" in str(error.value).lower()
    assert "deleted" not in str(error.value).lower()
    assert error.value.stage == "vector_store"


class FailedEmbeddings:
    model_name = "test-model"

    @staticmethod
    def embed_documents(texts):
        del texts
        raise EmbeddingServiceError(
            "Model cache is unavailable.", code="model_load_failed"
        )


class UntouchedVectorStore:
    called = False

    def delete_document_chunks(self, user_id, document_id) -> None:
        del user_id, document_id
        self.called = True


def test_embedding_diagnostic_code_is_preserved_without_touching_vectors() -> None:
    document = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), filename="annual-report.pdf"
    )
    chunk = SimpleNamespace(
        id=uuid4(),
        text="Revenue was $1 million.",
        page_numbers=[7],
        chunk_index=0,
    )
    vector_store = UntouchedVectorStore()

    with pytest.raises(DocumentIndexingError) as error:
        DocumentIndexingService(FailedEmbeddings(), vector_store).index_document(
            document, [chunk]
        )

    assert error.value.stage == "embedding"
    assert "model_load_failed" in str(error.value)
    assert vector_store.called is False


class PartialFailureVectorStore:
    delete_calls = 0

    def delete_document_chunks(self, user_id, document_id) -> None:
        del user_id, document_id
        self.delete_calls += 1

    @staticmethod
    def add_chunks(chunks, embeddings):
        del chunks, embeddings
        raise VectorStoreError("partial upsert failure")


def test_partial_vector_failure_triggers_cleanup() -> None:
    document = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), filename="annual-report.pdf"
    )
    chunk = SimpleNamespace(
        id=uuid4(),
        text="Revenue was $1 million.",
        page_numbers=[7],
        chunk_index=0,
    )
    vector_store = PartialFailureVectorStore()

    with pytest.raises(DocumentIndexingError) as error:
        DocumentIndexingService(Embeddings(), vector_store).index_document(
            document, [chunk]
        )

    assert error.value.stage == "vector_store"
    assert vector_store.delete_calls == 2
