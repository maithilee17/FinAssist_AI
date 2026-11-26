"""Opt-in real BGE extraction/chunking/embedding integration check."""

import math
import os
from pathlib import Path
from uuid import uuid4

import fitz
import pytest

from app.services.embedding_service import EmbeddingService
from app.services.pdf_processor import extract_pdf_pages
from app.services.text_chunker import chunk_pages


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_EMBEDDING_INTEGRATION") != "1",
    reason="Set RUN_EMBEDDING_INTEGRATION=1 with BGE weights available",
)
def test_real_bge_embeds_page_aware_financial_chunks(tmp_path: Path) -> None:
    source = tmp_path / "fictional-financial-report.pdf"
    pdf = fitz.open()
    first = pdf.new_page()
    first.insert_text((72, 72), "FY2025 revenue was USD 125.5 million.")
    second = pdf.new_page()
    second.insert_text((72, 72), "FY2024 revenue was USD 100.0 million.")
    pdf.save(source)
    pdf.close()

    document_id, user_id = uuid4(), uuid4()
    extraction = extract_pdf_pages(source, document_id, source.name)
    chunks = chunk_pages(
        extraction.pages,
        document_id=document_id,
        user_id=user_id,
        target_size=100,
        overlap_size=20,
    )
    service = EmbeddingService(
        "BAAI/bge-small-en-v1.5",
        device="cpu",
        batch_size=2,
        expected_dimension=384,
        model_revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        local_files_only=True,
    )

    vectors = service.embed_documents([chunk.text for chunk in chunks])

    assert extraction.page_count == 2
    assert chunks
    assert {page for chunk in chunks for page in chunk.page_numbers} == {1, 2}
    assert len(vectors) == len(chunks)
    assert all(len(vector) == 384 for vector in vectors)
    assert all(
        math.isclose(
            math.sqrt(sum(value * value for value in vector)), 1.0, abs_tol=1e-5
        )
        for vector in vectors
    )
