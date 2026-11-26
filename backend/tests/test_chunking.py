"""Page-aware chunk sizing, overlap, stability, and isolation tests."""

from uuid import uuid4

import pytest

from app.services.pdf_processor import ExtractedPage
from app.services.text_chunker import chunk_pages, estimate_token_count


def make_page(document_id, page_number: int, text: str) -> ExtractedPage:
    return ExtractedPage(
        document_id=document_id,
        filename="report.pdf",
        page_number=page_number,
        extracted_text=text,
    )


def test_chunk_size_overlap_and_stable_identifiers() -> None:
    document_id = uuid4()
    user_id = uuid4()
    text = " ".join(f"value{i}" for i in range(80))
    pages = [make_page(document_id, 1, text)]

    first = chunk_pages(
        pages, document_id=document_id, user_id=user_id, target_size=25, overlap_size=5
    )
    second = chunk_pages(
        pages, document_id=document_id, user_id=user_id, target_size=25, overlap_size=5
    )

    assert len(first) > 1
    assert all(chunk.token_count <= 25 for chunk in first)
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    first_tokens = set(first[0].text.split())
    second_tokens = set(first[1].text.split())
    assert len(first_tokens & second_tokens) >= 5


def test_chunks_retain_all_represented_page_numbers() -> None:
    document_id = uuid4()
    pages = [
        make_page(document_id, 1, "Page one revenue was $100 million."),
        make_page(document_id, 2, "Page two profit was €20 million."),
    ]
    chunks = chunk_pages(
        pages, document_id=document_id, user_id=uuid4(), target_size=50, overlap_size=5
    )

    assert len(chunks) == 1
    assert chunks[0].page_numbers == [1, 2]
    assert "$100" in chunks[0].text
    assert "€20" in chunks[0].text


def test_chunking_rejects_cross_document_pages() -> None:
    expected_document = uuid4()
    pages = [make_page(uuid4(), 1, "Unrelated document text")]
    with pytest.raises(ValueError, match="different documents"):
        chunk_pages(
            pages,
            document_id=expected_document,
            user_id=uuid4(),
            target_size=20,
            overlap_size=5,
        )


def test_chunking_preserves_each_paragraph() -> None:
    document_id = uuid4()
    markers = [f"UniqueParagraph{i} revenue -{i}.5%" for i in range(1, 8)]
    page = make_page(document_id, 1, "\n\n".join(markers))
    chunks = chunk_pages(
        [page], document_id=document_id, user_id=uuid4(), target_size=18, overlap_size=4
    )
    combined = "\n".join(chunk.text for chunk in chunks)

    assert all(marker in combined for marker in markers)
    assert all(
        chunk.token_count == estimate_token_count(chunk.text) for chunk in chunks
    )
