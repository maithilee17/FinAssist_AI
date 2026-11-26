"""ChromaDB-backed storage for user-isolated financial document embeddings."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class VectorStoreError(RuntimeError):
    """Raised when ChromaDB cannot complete an indexing or retrieval operation."""


@dataclass(frozen=True, slots=True)
class VectorChunk:
    id: UUID
    user_id: UUID
    document_id: UUID
    filename: str
    text: str
    page_numbers: list[int]
    chunk_index: int
    section: str | None = None


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    chunk_id: UUID
    user_id: UUID
    document_id: UUID
    filename: str
    page_numbers: list[int]
    chunk_text: str
    similarity_score: float
    section: str | None = None


class ChromaVectorStore:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        ssl: bool,
        collection_name: str,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.ssl = ssl
        self.collection_name = collection_name
        self._client_factory = client_factory
        self._client: Any | None = None
        self._collection: Any | None = None
        self._lock = Lock()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                if self._client_factory:
                    self._client = self._client_factory()
                else:
                    import chromadb

                    self._client = chromadb.HttpClient(
                        host=self.host, port=self.port, ssl=self.ssl
                    )
            except Exception as exc:
                logger.exception(
                    "ChromaDB client creation failed host=%s port=%s ssl=%s",
                    self.host,
                    self.port,
                    self.ssl,
                )
                raise VectorStoreError("ChromaDB is unavailable") from exc
        return self._client

    def _get_collection(self) -> Any:
        if self._collection is not None:
            return self._collection
        try:
            self._collection = self._get_client().get_or_create_collection(
                name=self.collection_name,
                configuration={"hnsw": {"space": "cosine"}},
                embedding_function=None,
            )
            return self._collection
        except Exception as exc:
            logger.exception(
                "ChromaDB collection open failed collection=%s", self.collection_name
            )
            raise VectorStoreError(
                "The ChromaDB collection could not be opened"
            ) from exc

    @staticmethod
    def _where(
        user_id: UUID, document_ids: Sequence[UUID] | None = None
    ) -> dict[str, Any]:
        user_filter: dict[str, Any] = {"user_id": {"$eq": str(user_id)}}
        if not document_ids:
            return user_filter
        document_values = [str(value) for value in dict.fromkeys(document_ids)]
        document_filter: dict[str, Any]
        if len(document_values) == 1:
            document_filter = {"document_id": {"$eq": document_values[0]}}
        else:
            document_filter = {"document_id": {"$in": document_values}}
        return {"$and": [user_filter, document_filter]}

    def add_chunks(
        self, chunks: Sequence[VectorChunk], embeddings: Sequence[Sequence[float]]
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Every chunk must have exactly one embedding")
        if not chunks:
            return 0
        dimension = len(embeddings[0])
        if dimension < 1:
            raise VectorStoreError("Embedding vectors must not be empty")
        if any(
            len(vector) != dimension
            or not all(math.isfinite(float(value)) for value in vector)
            for vector in embeddings
        ):
            raise VectorStoreError(
                "Embedding vectors must have one consistent finite dimension"
            )
        metadatas: list[dict[str, object]] = []
        for chunk in chunks:
            metadata: dict[str, object] = {
                "user_id": str(chunk.user_id),
                "document_id": str(chunk.document_id),
                "filename": chunk.filename,
                "page_numbers_json": json.dumps(chunk.page_numbers),
                "chunk_id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
            }
            if chunk.section:
                metadata["section"] = chunk.section
            metadatas.append(metadata)
        try:
            self._get_collection().upsert(
                ids=[str(chunk.id) for chunk in chunks],
                embeddings=[list(vector) for vector in embeddings],
                documents=[chunk.text for chunk in chunks],
                metadatas=metadatas,
            )
            return len(chunks)
        except Exception as exc:
            logger.exception(
                "ChromaDB upsert failed collection=%s chunks=%s dimension=%s",
                self.collection_name,
                len(chunks),
                dimension,
            )
            raise VectorStoreError(
                "Document embeddings could not be stored in ChromaDB. Check the "
                "collection health and embedding dimension."
            ) from exc

    def search_similar_chunks(
        self,
        query_embedding: Sequence[float],
        *,
        user_id: UUID,
        document_ids: Sequence[UUID] | None = None,
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        if not query_embedding or not all(
            math.isfinite(float(value)) for value in query_embedding
        ):
            raise VectorStoreError("The query embedding is empty or invalid")
        try:
            collection = self._get_collection()
            if collection.count() == 0:
                return []
            response = collection.query(
                query_embeddings=[list(query_embedding)],
                n_results=top_k,
                where=self._where(user_id, document_ids),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.exception(
                "ChromaDB query failed collection=%s top_k=%s selected_documents=%s",
                self.collection_name,
                top_k,
                len(document_ids or []),
            )
            raise VectorStoreError("Semantic retrieval from ChromaDB failed") from exc

        ids = (response.get("ids") or [[]])[0]
        documents = (response.get("documents") or [[]])[0]
        metadatas = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]
        results: list[VectorSearchResult] = []
        seen: set[str] = set()
        for chunk_id, text, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            if chunk_id in seen or not metadata or text is None:
                continue
            seen.add(chunk_id)
            try:
                page_numbers = [
                    int(value) for value in json.loads(metadata["page_numbers_json"])
                ]
                score = max(-1.0, min(1.0, 1.0 - float(distance)))
                results.append(
                    VectorSearchResult(
                        chunk_id=UUID(str(metadata.get("chunk_id", chunk_id))),
                        user_id=UUID(str(metadata["user_id"])),
                        document_id=UUID(str(metadata["document_id"])),
                        filename=str(metadata["filename"]),
                        page_numbers=page_numbers,
                        chunk_text=str(text),
                        similarity_score=score,
                        section=str(metadata["section"])
                        if metadata.get("section")
                        else None,
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise VectorStoreError(
                    "ChromaDB returned malformed chunk metadata"
                ) from exc
        return results

    def count_document_chunks(self, user_id: UUID, document_id: UUID) -> int:
        try:
            response = self._get_collection().get(
                where=self._where(user_id, [document_id]), include=[]
            )
            return len(response.get("ids") or [])
        except Exception as exc:
            logger.exception(
                "ChromaDB document count failed collection=%s", self.collection_name
            )
            raise VectorStoreError("Indexed chunk count could not be verified") from exc

    def delete_document_chunks(self, user_id: UUID, document_id: UUID) -> None:
        try:
            self._get_collection().delete(where=self._where(user_id, [document_id]))
        except Exception as exc:
            logger.exception(
                "ChromaDB document delete failed collection=%s", self.collection_name
            )
            raise VectorStoreError("Document vectors could not be deleted") from exc

    def delete_user_chunks(self, user_id: UUID) -> None:
        try:
            self._get_collection().delete(where=self._where(user_id))
        except Exception as exc:
            logger.exception(
                "ChromaDB user delete failed collection=%s", self.collection_name
            )
            raise VectorStoreError("User vectors could not be deleted") from exc

    def health_check(self) -> bool:
        try:
            return bool(self._get_client().heartbeat())
        except Exception as exc:
            logger.exception(
                "ChromaDB heartbeat failed host=%s port=%s", self.host, self.port
            )
            raise VectorStoreError("ChromaDB health check failed") from exc
