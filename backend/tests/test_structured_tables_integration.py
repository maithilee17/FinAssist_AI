"""Isolated SQL integration; fake retrieval/LLM, real PDF extraction and proof verification.

This is not a live Chroma/Ollama test. Uses the existing isolated database fixture.
"""

import pytest
from app.models.document import Document, DocumentChunk, DocumentPage
from app.services.financial_table_extractor import decode_table_chunk
from app.services.pdf_processor import extract_pdf_pages
from app.services.rag_pipeline import RagAccessError, RagPipeline
from app.services.text_chunker import chunk_pages
from app.services.vector_store import VectorSearchResult

from tests.table_fixtures import make_fixture
from tests.test_rag_pipeline import FakeLLM, FakeRetrieval, create_indexed_document

pytestmark = pytest.mark.anyio


async def test_table_metadata_roundtrip_and_real_sql_context_expansion(
    session_factory, tmp_path
):
    user, doc = await create_indexed_document(
        session_factory, "structured-owner@example.com"
    )
    outsider, _ = await create_indexed_document(
        session_factory, "structured-outsider@example.com"
    )
    path = make_fixture(tmp_path / "comparative.pdf", "three_year")
    extracted = extract_pdf_pages(path, doc, path.name)
    chunks = chunk_pages(
        extracted.pages, document_id=doc, user_id=user, target_size=85, overlap_size=20
    )
    async with session_factory() as db:
        document = await db.get(Document, doc)
        document.page_count = 1
        document.indexed_chunk_count = len(chunks)
        for page in extracted.pages:
            db.add(
                DocumentPage(
                    document_id=doc,
                    page_number=page.page_number,
                    extracted_text=page.extracted_text,
                    extraction_metadata=page.metadata,
                )
            )
        db.add_all(
            [
                DocumentChunk(
                    id=c.id,
                    user_id=user,
                    document_id=doc,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    token_count=c.token_count,
                    page_numbers=c.page_numbers,
                )
                for c in chunks
            ]
        )
        await db.commit()
    revenue = next(
        c
        for c in chunks
        if (t := decode_table_chunk(c.text)) and t.rows[0].label == "Revenue"
    )
    seed = VectorSearchResult(
        revenue.id, user, doc, "annual-report.pdf", [1], revenue.text, 0.9
    )
    llm = FakeLLM()
    pipeline = RagPipeline(FakeRetrieval([seed]), llm)
    async with session_factory() as db:
        result = await pipeline.answer(
            db,
            user_id=user,
            document_ids=[doc],
            question="Calculate net profit margin in FY2025",
        )
        assert "7.58%" in result.answer
        assert result.sources and all(
            s.document_id == doc and s.page_numbers == [1] for s in result.sources
        )
        assert not llm.calls
        with pytest.raises(RagAccessError):
            await pipeline.answer(
                db,
                user_id=outsider,
                document_ids=[doc],
                question="Calculate net profit margin in FY2025",
            )
