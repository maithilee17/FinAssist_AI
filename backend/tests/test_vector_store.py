"""Chroma adapter upsert, filtering, isolation, and deletion tests."""

from uuid import uuid4

import pytest

from app.services.vector_store import ChromaVectorStore, VectorChunk, VectorStoreError


def matches(metadata, where) -> bool:
    if "$and" in where:
        return all(matches(metadata, item) for item in where["$and"])
    key, condition = next(iter(where.items()))
    if "$eq" in condition:
        return metadata.get(key) == condition["$eq"]
    if "$in" in condition:
        return metadata.get(key) in condition["$in"]
    return False


class FakeCollection:
    def __init__(self) -> None:
        self.records = {}

    def upsert(self, *, ids, embeddings, documents, metadatas) -> None:
        for values in zip(ids, embeddings, documents, metadatas, strict=True):
            self.records[values[0]] = values[1:]

    def count(self) -> int:
        return len(self.records)

    def query(self, *, query_embeddings, n_results, where, include):
        del include
        query = query_embeddings[0]
        candidates = []
        for identifier, (embedding, document, metadata) in self.records.items():
            if matches(metadata, where):
                similarity = sum(a * b for a, b in zip(query, embedding, strict=True))
                candidates.append((similarity, identifier, document, metadata))
        candidates.sort(reverse=True)
        candidates = candidates[:n_results]
        return {
            "ids": [[item[1] for item in candidates]],
            "documents": [[item[2] for item in candidates]],
            "metadatas": [[item[3] for item in candidates]],
            "distances": [[1.0 - item[0] for item in candidates]],
        }

    def get(self, *, where, include):
        del include
        return {
            "ids": [
                identifier
                for identifier, (_, _, metadata) in self.records.items()
                if matches(metadata, where)
            ]
        }

    def delete(self, *, where) -> None:
        self.records = {
            identifier: values
            for identifier, values in self.records.items()
            if not matches(values[2], where)
        }


class FakeClient:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def get_or_create_collection(self, **kwargs):
        assert kwargs["embedding_function"] is None
        assert kwargs["configuration"]["hnsw"]["space"] == "cosine"
        return self.collection

    @staticmethod
    def heartbeat() -> int:
        return 1


def chunk(user_id, document_id, text, page, index=0) -> VectorChunk:
    return VectorChunk(
        id=uuid4(),
        user_id=user_id,
        document_id=document_id,
        filename=f"report-{document_id}.pdf",
        text=text,
        page_numbers=[page],
        chunk_index=index,
    )


def test_upsert_search_filters_duplicates_and_deletion() -> None:
    client = FakeClient()
    store = ChromaVectorStore(
        host="test",
        port=8000,
        ssl=False,
        collection_name="test",
        client_factory=lambda: client,
    )
    user_one, user_two = uuid4(), uuid4()
    document_one, document_two = uuid4(), uuid4()
    first = chunk(user_one, document_one, "Revenue was 100", 3)
    second = chunk(user_one, document_two, "Profit was 20", 7)
    foreign = chunk(user_two, document_one, "Private foreign data", 9)

    assert store.add_chunks([first, second, foreign], [[1, 0], [0, 1], [1, 0]]) == 3
    assert store.add_chunks([first], [[1, 0]]) == 1
    assert client.collection.count() == 3
    all_owned = store.search_similar_chunks([1, 0], user_id=user_one, top_k=5)
    selected = store.search_similar_chunks(
        [0, 1], user_id=user_one, document_ids=[document_two], top_k=5
    )

    assert {result.chunk_id for result in all_owned} == {first.id, second.id}
    assert [result.chunk_id for result in selected] == [second.id]
    assert all(result.user_id == user_one for result in all_owned)
    assert selected[0].page_numbers == [7]
    assert store.count_document_chunks(user_one, document_one) == 1
    store.delete_document_chunks(user_one, document_one)
    assert store.count_document_chunks(user_one, document_one) == 0
    assert store.count_document_chunks(user_two, document_one) == 1
    store.delete_user_chunks(user_two)
    assert store.count_document_chunks(user_two, document_one) == 0
    assert store.health_check() is True


@pytest.mark.parametrize(
    "embeddings",
    [
        [[]],
        [[1.0, float("nan")]],
        [[1.0, 0.0], [1.0]],
    ],
)
def test_invalid_vectors_are_rejected_before_chromadb(embeddings) -> None:
    client = FakeClient()
    store = ChromaVectorStore(
        host="test",
        port=8000,
        ssl=False,
        collection_name="test",
        client_factory=lambda: client,
    )
    user_id, document_id = uuid4(), uuid4()
    chunks = [
        chunk(user_id, document_id, "Revenue", 1, index)
        for index in range(len(embeddings))
    ]

    with pytest.raises(VectorStoreError):
        store.add_chunks(chunks, embeddings)

    assert client.collection.count() == 0


def test_invalid_query_vector_is_rejected_before_chromadb() -> None:
    store = ChromaVectorStore(
        host="test",
        port=8000,
        ssl=False,
        collection_name="test",
        client_factory=FakeClient,
    )

    with pytest.raises(VectorStoreError):
        store.search_similar_chunks([], user_id=uuid4())
