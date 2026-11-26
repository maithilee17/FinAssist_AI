"""Sentence Transformers service behavior without downloading model weights."""

import math
from typing import ClassVar

import pytest

from app.services.embedding_service import EmbeddingService, EmbeddingServiceError


class FakeSentenceTransformer:
    loads = 0

    def __init__(self, model_name: str, **kwargs) -> None:
        type(self).loads += 1
        self.model_name = model_name
        self.kwargs = kwargs
        self.query_kwargs = {}
        self.document_kwargs = {}

    def encode_document(self, texts, **kwargs):
        self.document_kwargs = kwargs
        return [[1.0, 0.0, 0.0] for _ in texts]

    def encode_query(self, texts, **kwargs):
        self.query_kwargs = kwargs
        return [[0.0, 1.0, 0.0] for _ in texts]

    @staticmethod
    def get_sentence_embedding_dimension() -> int:
        return 3


def test_document_and_query_embeddings_are_normalized_and_dimensionally_consistent() -> (
    None
):
    FakeSentenceTransformer.loads = 0
    service = EmbeddingService(
        "BAAI/bge-small-en-v1.5",
        device="cpu",
        query_prefix="Represent this sentence: ",
        expected_dimension=3,
        model_factory=FakeSentenceTransformer,
    )

    documents = service.embed_documents(["Revenue was $10m", "Profit was $2m"])
    query = service.embed_query("What was revenue?")

    assert len(documents) == 2
    assert len(documents[0]) == len(query) == service.dimension == 3
    assert FakeSentenceTransformer.loads == 1
    assert service._model.document_kwargs["normalize_embeddings"] is True
    assert service._model.query_kwargs["normalize_embeddings"] is True
    assert service._model.query_kwargs["prompt"] == "Represent this sentence: "


def test_empty_document_batch_does_not_load_model() -> None:
    FakeSentenceTransformer.loads = 0
    service = EmbeddingService("test", model_factory=FakeSentenceTransformer)
    assert service.embed_documents([]) == []
    assert FakeSentenceTransformer.loads == 0


class InvalidOutputModel(FakeSentenceTransformer):
    output: ClassVar[list[list[float]]] = [[1.0, 0.0, 0.0]]

    def encode_document(self, texts, **kwargs):
        del texts, kwargs
        return self.output


@pytest.mark.parametrize(
    ("output", "code"),
    [
        ([[1.0, 0.0]], "embedding_dimension_mismatch"),
        ([[math.nan, 0.0, 0.0]], "non_finite_embedding"),
        ([[0.0, 0.0, 0.0]], "empty_embedding"),
        ([[2.0, 0.0, 0.0]], "unnormalized_embedding"),
        ([], "embedding_count_mismatch"),
    ],
)
def test_invalid_embedding_outputs_fail_closed(output, code) -> None:
    InvalidOutputModel.output = output
    service = EmbeddingService(
        "test", expected_dimension=3, model_factory=InvalidOutputModel
    )

    with pytest.raises(EmbeddingServiceError) as error:
        service.embed_documents(["financial evidence"])

    assert error.value.code == code


def test_model_dimension_mismatch_is_actionable() -> None:
    service = EmbeddingService(
        "test", expected_dimension=384, model_factory=FakeSentenceTransformer
    )

    with pytest.raises(EmbeddingServiceError) as error:
        service.embed_documents(["financial evidence"])

    assert error.value.code == "model_dimension_mismatch"
    assert "3 != 384" in str(error.value)


def test_model_load_failure_preserves_safe_diagnostic_code() -> None:
    def broken_factory(model_name: str, **kwargs):
        del model_name, kwargs
        raise PermissionError("private cache path must not reach the client")

    service = EmbeddingService("test", model_factory=broken_factory)

    with pytest.raises(EmbeddingServiceError) as error:
        service.embed_documents(["financial evidence"])

    assert error.value.code == "model_load_failed"
    assert "private cache path" not in str(error.value)
    assert isinstance(error.value.__cause__, PermissionError)


def test_diagnostic_check_runs_document_and_query_inference() -> None:
    service = EmbeddingService(
        "test", expected_dimension=3, model_factory=FakeSentenceTransformer
    )

    diagnostic = service.diagnostic_check()

    assert diagnostic == {
        "status": "ok",
        "model": "test",
        "device": "cpu",
        "dimension": 3,
        "document_vectors": 2,
        "query_vectors": 1,
        "finite": True,
    }
