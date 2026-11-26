"""Reusable, validated Sentence Transformers embeddings for financial text."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingServiceError(RuntimeError):
    """Safe embedding failure with a stable diagnostic code."""

    def __init__(self, message: str, *, code: str = "embedding_failed") -> None:
        super().__init__(message)
        self.code = code


class EmbeddingService:
    def __init__(
        self,
        model_name: str,
        *,
        device: str | None = "cpu",
        batch_size: int = 32,
        query_prefix: str = "",
        expected_dimension: int | None = None,
        model_revision: str | None = None,
        local_files_only: bool = False,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.query_prefix = query_prefix
        self.expected_dimension = expected_dimension
        self.model_revision = model_revision
        self.local_files_only = local_files_only
        self._model_factory = model_factory
        self._model: Any | None = None
        self._load_lock = Lock()
        self._encode_lock = Lock()

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                if self._model_factory is None:
                    from sentence_transformers import SentenceTransformer

                    factory: Callable[..., Any] = SentenceTransformer
                else:
                    factory = self._model_factory
                kwargs: dict[str, object] = {
                    "local_files_only": self.local_files_only,
                    "trust_remote_code": False,
                }
                if self.device:
                    kwargs["device"] = self.device
                if self.model_revision:
                    kwargs["revision"] = self.model_revision
                self._model = factory(self.model_name, **kwargs)
                self._validate_model_dimension(self._model)
            except EmbeddingServiceError:
                self._model = None
                raise
            except Exception as exc:
                self._model = None
                logger.exception(
                    "Embedding model load failed model=%s device=%s local_only=%s",
                    self.model_name,
                    self.device or "auto",
                    self.local_files_only,
                )
                raise EmbeddingServiceError(
                    "The embedding model could not be loaded. Check model-cache "
                    "permissions, download completeness, and the CPU runtime.",
                    code="model_load_failed",
                ) from exc
        return self._model

    def _validate_model_dimension(self, model: Any) -> int:
        try:
            dimension_getter = getattr(model, "get_embedding_dimension", None)
            if dimension_getter is None:
                dimension_getter = model.get_sentence_embedding_dimension
            dimension = dimension_getter()
        except Exception as exc:
            raise EmbeddingServiceError(
                "The embedding model dimension could not be determined.",
                code="model_dimension_unavailable",
            ) from exc
        if not dimension or int(dimension) < 1:
            raise EmbeddingServiceError(
                "The embedding model did not report a valid vector dimension.",
                code="model_dimension_unavailable",
            )
        dimension = int(dimension)
        if self.expected_dimension and dimension != self.expected_dimension:
            raise EmbeddingServiceError(
                "The embedding model dimension does not match the configured dimension "
                f"({dimension} != {self.expected_dimension}).",
                code="model_dimension_mismatch",
            )
        return dimension

    @staticmethod
    def _as_lists(values: Any) -> list[list[float]]:
        if values is None:
            return []
        if hasattr(values, "tolist"):
            values = values.tolist()
        if not isinstance(values, list):
            values = list(values)
        if values and isinstance(values[0], (int, float)):
            values = [values]
        try:
            return [[float(number) for number in row] for row in values]
        except (TypeError, ValueError) as exc:
            raise EmbeddingServiceError(
                "The embedding model returned an invalid vector structure.",
                code="invalid_embedding_output",
            ) from exc

    def _validate_vectors(
        self, vectors: list[list[float]], *, expected_count: int
    ) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise EmbeddingServiceError(
                "The embedding model returned an unexpected number of vectors.",
                code="embedding_count_mismatch",
            )
        model_dimension = self.dimension
        for index, vector in enumerate(vectors):
            if len(vector) != model_dimension:
                raise EmbeddingServiceError(
                    "The embedding model returned inconsistent vector dimensions "
                    f"at batch position {index}.",
                    code="embedding_dimension_mismatch",
                )
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingServiceError(
                    "The embedding model returned a non-finite vector.",
                    code="non_finite_embedding",
                )
            norm = math.sqrt(math.fsum(value * value for value in vector))
            if norm <= 0.0:
                raise EmbeddingServiceError(
                    "The embedding model returned an empty vector.",
                    code="empty_embedding",
                )
            if not 0.99 <= norm <= 1.01:
                raise EmbeddingServiceError(
                    "The embedding model returned a vector that was not normalized.",
                    code="unnormalized_embedding",
                )
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        from app.services.financial_table_extractor import (
            decode_table_chunk,
            render_table,
        )

        cleaned = [render_table(table) if (table := decode_table_chunk(text)) else text.strip() for text in texts]
        if not cleaned:
            return []
        if any(not text for text in cleaned):
            raise EmbeddingServiceError(
                "Document chunks must contain non-empty text.",
                code="empty_document_chunk",
            )
        model = self._load_model()
        try:
            encoder = getattr(model, "encode_document", None) or model.encode
            with self._encode_lock:
                values = encoder(
                    cleaned,
                    batch_size=self.batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        except Exception as exc:
            logger.exception(
                "Document embedding inference failed model=%s chunks=%s batch_size=%s",
                self.model_name,
                len(cleaned),
                self.batch_size,
            )
            raise EmbeddingServiceError(
                "Document embeddings could not be generated. Check available memory, "
                "the configured batch size, and model-cache integrity.",
                code="document_inference_failed",
            ) from exc
        return self._validate_vectors(
            self._as_lists(values), expected_count=len(cleaned)
        )

    def embed_query(self, question: str) -> list[float]:
        question = question.strip()
        if not question:
            raise EmbeddingServiceError(
                "Question must not be empty.", code="empty_query"
            )
        model = self._load_model()
        try:
            encoder = getattr(model, "encode_query", None) or model.encode
            kwargs: dict[str, object] = {
                "batch_size": 1,
                "normalize_embeddings": True,
                "convert_to_numpy": True,
                "show_progress_bar": False,
            }
            if self.query_prefix:
                kwargs["prompt"] = self.query_prefix
            with self._encode_lock:
                values = encoder([question], **kwargs)
        except Exception as exc:
            logger.exception(
                "Query embedding inference failed model=%s", self.model_name
            )
            raise EmbeddingServiceError(
                "The question embedding could not be generated.",
                code="query_inference_failed",
            ) from exc
        vectors = self._validate_vectors(self._as_lists(values), expected_count=1)
        return vectors[0]

    @property
    def dimension(self) -> int:
        return self._validate_model_dimension(self._load_model())

    def diagnostic_check(self) -> dict[str, object]:
        """Run a small real inference without exposing model inputs or cache paths."""
        documents = self.embed_documents(
            ["Revenue was $10 million.", "Operating profit was $2 million."]
        )
        query = self.embed_query("What was revenue?")
        return {
            "status": "ok",
            "model": self.model_name,
            "device": self.device or "auto",
            "dimension": self.dimension,
            "document_vectors": len(documents),
            "query_vectors": 1,
            "finite": all(
                math.isfinite(value)
                for vector in [*documents, query]
                for value in vector
            ),
        }
