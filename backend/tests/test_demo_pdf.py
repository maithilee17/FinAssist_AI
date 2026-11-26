"""Regression tests for the fictional acceptance-test PDF generator."""

from uuid import uuid4

import pytest

from app.diagnostics.demo_pdf import create_demo_pdf
from app.services.pdf_processor import extract_pdf_pages


def test_demo_pdf_is_page_aware_and_contains_known_financial_evidence(tmp_path) -> None:
    destination = tmp_path / "fictional-financial-report.pdf"
    create_demo_pdf(destination)

    result = extract_pdf_pages(destination, uuid4(), destination.name)

    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert "USD 125.5 million" in result.pages[0].extracted_text
    assert "20.0%" in result.pages[1].extracted_text
    normalized_page = " ".join(result.pages[2].extracted_text.split())
    assert "does not disclose a debt-to-equity ratio" in normalized_page


def test_demo_pdf_refuses_to_overwrite_existing_file(tmp_path) -> None:
    destination = tmp_path / "fictional-financial-report.pdf"
    create_demo_pdf(destination)

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        create_demo_pdf(destination)
