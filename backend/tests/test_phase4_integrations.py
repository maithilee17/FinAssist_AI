"""Opt-in integration checks for externally configured Phase 4 services."""

import os
from uuid import uuid4

import pytest

from app.config import get_settings
from app.services.llm_service import create_llm_service
from app.services.vector_store import ChromaVectorStore, VectorChunk


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_CHROMA_INTEGRATION") != "1",
    reason="Set RUN_CHROMA_INTEGRATION=1 with ChromaDB running",
)
def test_real_chromadb_round_trip() -> None:
    settings = get_settings()
    collection = f"finassist_integration_{uuid4().hex}"
    store = ChromaVectorStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
        collection_name=collection,
    )
    user_id, document_id, chunk_id = uuid4(), uuid4(), uuid4()
    chunk = VectorChunk(
        id=chunk_id,
        user_id=user_id,
        document_id=document_id,
        filename="integration.pdf",
        text="Revenue was 100 million.",
        page_numbers=[2],
        chunk_index=0,
    )
    assert store.health_check()
    assert store.add_chunks([chunk], [[1.0, 0.0, 0.0]]) == 1
    assert (
        store.search_similar_chunks([1.0, 0.0, 0.0], user_id=user_id)[0].chunk_id
        == chunk_id
    )
    store.delete_document_chunks(user_id, document_id)
    assert store.count_document_chunks(user_id, document_id) == 0


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_INTEGRATION") != "1",
    reason="Set RUN_OLLAMA_INTEGRATION=1 with local Ollama running",
)
async def test_real_ollama_generation_returns_text() -> None:
    service = create_llm_service(get_settings())
    await service.check_health()
    result = await service.generate(
        "Answer using only supplied evidence.",
        "Evidence: Revenue was 100. Question: What was revenue?",
    )
    assert result.answer.strip()
    assert "100" in result.answer
    assert result.model_name
