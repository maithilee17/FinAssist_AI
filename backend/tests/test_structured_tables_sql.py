"""Real isolated SQLite/PDF/RAG integration with a synchronous SQL async facade.

Retrieval and LLM are test doubles; no live services or production data are used.
The facade avoids the restricted Windows socket-based event loop during this test.
"""

import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.database import Base
from app.models import Document, DocumentChunk, DocumentPage, DocumentStatus, User
from app.services.financial_table_extractor import decode_table_chunk
from app.services.pdf_processor import extract_pdf_pages
from app.services.rag_pipeline import RagAccessError, RagPipeline
from app.services.text_chunker import chunk_pages
from app.services.vector_store import VectorSearchResult
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tests.table_fixtures import make_fixture
from tests.test_rag_pipeline import FakeLLM, FakeRetrieval
from tests.test_structured_financial_tables import immediate


def test_real_sql_table_expansion_and_rag_proof(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    user, outsider, doc = uuid4(), uuid4(), uuid4()
    path = make_fixture(tmp_path / "comparative.pdf", "three_year")
    extracted = extract_pdf_pages(path, doc, path.name)
    chunks = chunk_pages(
        extracted.pages, document_id=doc, user_id=user, target_size=85, overlap_size=20
    )
    with Session(engine) as db:
        db.add_all(
            [
                User(
                    id=uid,
                    full_name="Fixture",
                    email=f"{uid}@example.test",
                    hashed_password="unused-test-hash",
                )
                for uid in (user, outsider)
            ]
        )
        db.add(
            Document(
                id=doc,
                user_id=user,
                filename=path.name,
                storage_path="fixture.pdf",
                file_size=path.stat().st_size,
                mime_type="application/pdf",
                page_count=1,
                processing_status=DocumentStatus.COMPLETED,
                indexed_chunk_count=len(chunks),
                indexed_at=datetime.now(UTC),
            )
        )
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
        db.commit()
        db.expire_all()
        page = db.scalars(
            select(DocumentPage).where(DocumentPage.document_id == doc)
        ).one()
        assert (
            page.extraction_metadata["financial_tables"][0]["rows"][0]["cells"][1][
                "value"
            ]
            == "1200000"
        )

        class SqlFacade:
            async def execute(self, statement):
                return db.execute(statement)

            async def scalars(self, statement):
                return db.scalars(statement)

        seed_chunk = next(
            c
            for c in chunks
            if (t := decode_table_chunk(c.text)) and t.rows[0].label == "Revenue"
        )
        seed = VectorSearchResult(
            seed_chunk.id, user, doc, path.name, [1], seed_chunk.text, 0.9
        )
        assert "Net Income" not in seed.chunk_text
        llm = FakeLLM()
        pipeline = RagPipeline(FakeRetrieval([seed]), llm)
        result = immediate(
            pipeline.answer(
                SqlFacade(),
                user_id=user,
                document_ids=[doc],
                question="Calculate net profit margin in FY2025",
            )
        )
        assert "7.58%" in result.answer and not llm.calls
        assert result.retrieved_chunks_count > 1
        assert result.sources and all(
            s.document_id == doc and s.page_numbers == [1] for s in result.sources
        )
        cited = {int(n) for n in re.findall(r"\[Source (\d+)\]", result.answer)}
        assert len(cited) == 2
        assert all("table " in result.sources[n - 1].excerpt for n in cited)
        with pytest.raises(RagAccessError):
            immediate(
                pipeline.answer(
                    SqlFacade(),
                    user_id=outsider,
                    document_ids=[doc],
                    question="Calculate net profit margin in FY2025",
                )
            )
    engine.dispose()
