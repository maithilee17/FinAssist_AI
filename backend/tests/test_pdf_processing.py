"""PyMuPDF extraction, cleaning, empty-page, and invalid-file tests."""

from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest

from app.services.pdf_processor import (
    EncryptedPdfError,
    InvalidPdfError,
    extract_pdf_pages,
    inspect_pdf,
)
from app.services.text_cleaner import clean_extracted_text


def test_multi_page_extraction_preserves_pages_unicode_and_financial_values(
    tmp_path, pdf_bytes_factory
) -> None:
    source = tmp_path / "financial-report.pdf"
    source.write_bytes(
        pdf_bytes_factory(
            [
                "FY2025 Revenue: ₹1,250.50<br>Operating margin: -3.2%",
                "FY2024 Revenue: €980.25<br>Report date: 31 March 2025",
            ]
        )
    )

    document_id = uuid4()
    result = extract_pdf_pages(source, document_id, "financial-report.pdf")

    assert result.page_count == 2
    assert [page.page_number for page in result.pages] == [1, 2]
    assert "FY2025" in result.pages[0].extracted_text
    assert "1,250.50" in result.pages[0].extracted_text
    assert "-3.2%" in result.pages[0].extracted_text
    assert "€980.25" in result.pages[1].extracted_text
    assert result.pages[0].document_id == document_id


def test_empty_page_is_preserved(tmp_path, pdf_bytes_factory) -> None:
    source = tmp_path / "with-empty-page.pdf"
    source.write_bytes(pdf_bytes_factory(["First page text", "", "Third page text"]))

    result = extract_pdf_pages(source, uuid4(), source.name)

    assert result.page_count == 3
    assert result.pages[1].page_number == 2
    assert result.pages[1].extracted_text == ""
    assert result.pages[1].metadata["is_empty"] is True


def test_pdf_opener_does_not_read_the_complete_file_into_python_memory(
    tmp_path, pdf_bytes_factory, monkeypatch
) -> None:
    source = tmp_path / "path-backed.pdf"
    source.write_bytes(pdf_bytes_factory(["Revenue was $42 million in FY2025."]))

    def fail_full_read(_path: Path) -> bytes:
        raise AssertionError("Path.read_bytes must not be used for PDF validation")

    monkeypatch.setattr(Path, "read_bytes", fail_full_read)

    assert inspect_pdf(source) == 1
    source.unlink()
    assert not source.exists()


def test_invalid_and_corrupted_pdf_are_rejected(tmp_path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a pdf")
    with pytest.raises(InvalidPdfError):
        inspect_pdf(invalid)

    corrupted = tmp_path / "corrupted.pdf"
    corrupted.write_bytes(b"%PDF-1.7\nthis is not a complete PDF")
    with pytest.raises(InvalidPdfError):
        inspect_pdf(corrupted)
    corrupted.unlink()
    assert not corrupted.exists()


def test_encrypted_pdf_is_rejected(tmp_path) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Confidential")
    encrypted_bytes = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    document.close()
    source = tmp_path / "encrypted.pdf"
    source.write_bytes(encrypted_bytes)

    with pytest.raises(EncryptedPdfError):
        inspect_pdf(source)


def test_cleaner_preserves_financial_meaning_and_paragraphs() -> None:
    raw = "Revenue\u00a0 ₹ 1,250.50   \nMargin -3.2%\n\n\nFY2025\t31/03/2025"
    cleaned = clean_extracted_text(raw)

    assert "₹ 1,250.50" in cleaned
    assert "-3.2%" in cleaned
    assert "\n\n" in cleaned
    assert "FY2025" in cleaned
    assert "31/03/2025" in cleaned
