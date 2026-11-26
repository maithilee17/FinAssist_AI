"""Comprehensive Phase 3C OCR and Scanned Financial PDF test suite."""

from decimal import Decimal
from uuid import uuid4

import pymupdf
import pytest

from app.config import get_settings
from app.services.financial_calculation import calculate
from app.services.financial_table_extractor import FinancialTable
from app.services.ocr_service import OcrService, resolve_tessdata_path
from app.services.pdf_page_classifier import PageExtractionMode, classify_pdf_page
from app.services.pdf_processor import extract_pdf_pages
from app.services.scanned_table_reconstructor import (
    _clean_ocr_numeric_substitutions,
    reconstruct_scanned_financial_tables,
)
from app.services.text_chunker import _page_units
from app.services.vector_store import VectorSearchResult
from tests.ocr_test_fixtures import (
    SCANNED_BALANCE_METRICS,
    SCANNED_INCOME_METRICS,
    create_mixed_digital_scanned_pdf,
    create_oversized_pixel_bomb_pdf,
    create_scanned_balance_sheet_pdf,
    create_scanned_cash_flow_pdf,
    create_scanned_income_statement_pdf,
)


def test_tessdata_path_is_resolved() -> None:
    path = resolve_tessdata_path()
    assert path is not None
    assert (
        (path.endswith("tessdata") and "eng.traineddata")
        or "tessdata" in path.lower()
    )


def test_classify_digital_text_page(tmp_path) -> None:
    pdf_path = tmp_path / "digital_text.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((54, 100), "Annual Financial Report FY2025", fontsize=14)
    page.insert_textbox(
        pymupdf.Rect(54, 130, 550, 400),
        "Apex Global Technologies is an advanced electronics manufacturer.\n"
        "Revenue increased 26.32% in FY2025 to $1,200,000 USD.\n"
        "Cost of sales was $780,000 and gross profit was $420,000.\n"
        "Operating expenses remained stable throughout the reporting period.",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()

    verify_doc = pymupdf.open(str(pdf_path))
    classification = classify_pdf_page(verify_doc[0], page_number=1)
    verify_doc.close()

    assert classification.mode == PageExtractionMode.DIGITAL_TEXT
    assert classification.requires_ocr is False
    assert classification.digital_char_count > 100
    assert classification.image_count == 0


def test_classify_image_only_scanned_page(tmp_path) -> None:
    pdf_path = create_scanned_income_statement_pdf(tmp_path / "scanned.pdf")
    doc = pymupdf.open(str(pdf_path))
    classification = classify_pdf_page(doc[0], page_number=1)
    doc.close()

    assert classification.mode == PageExtractionMode.IMAGE_ONLY
    assert classification.requires_ocr is True
    assert classification.digital_char_count == 0
    assert classification.image_count == 1
    assert classification.image_area_ratio >= 0.80


def test_classify_oversized_pixel_bomb(tmp_path) -> None:
    pdf_path = create_oversized_pixel_bomb_pdf(tmp_path / "bomb.pdf")
    doc = pymupdf.open(str(pdf_path))
    classification = classify_pdf_page(doc[0], page_number=1, max_pixels=25_000_000)
    doc.close()

    assert classification.mode == PageExtractionMode.OCR_UNSUPPORTED
    assert classification.requires_ocr is False
    assert any("exceeds maximum limit" in r for r in classification.reasons)


def test_clean_ocr_numeric_substitutions() -> None:
    # 1. 'O' / 'o' in numbers
    res, sub = _clean_ocr_numeric_substitutions("1,2OO,OOO")
    assert res == "1,200,000"
    assert sub is True

    res, sub = _clean_ocr_numeric_substitutions("(78O,OOO)")
    assert res == "(780,000)"
    assert sub is True

    # 2. 'l' / 'I' in numbers
    res, sub = _clean_ocr_numeric_substitutions("l,200,000")
    assert res == "1,200,000"
    assert sub is True

    res, sub = _clean_ocr_numeric_substitutions("I,950,000")
    assert res == "1,950,000"
    assert sub is True

    # 3. Normal clean number
    res, sub = _clean_ocr_numeric_substitutions("420,000")
    assert res == "420,000"
    assert sub is False


def test_scanned_income_statement_multi_year_reconstruction(tmp_path) -> None:
    pdf_path = create_scanned_income_statement_pdf(tmp_path / "income.pdf")
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "income.pdf")
    assert result.page_count == 1
    page = result.pages[0]

    assert page.metadata["ocr_applied"] is True
    assert page.metadata["page_mode"] == "image_only"
    assert page.metadata["ocr_words_count"] > 25

    tables_data = page.metadata.get("financial_tables", [])
    assert len(tables_data) == 1
    table = FinancialTable.model_validate(tables_data[0])

    assert table.status == "certain"
    assert table.method == "Tesseract.ocr/scanned_table"
    assert len(table.columns) == 4

    # Check periods
    periods = [c.period for c in table.columns if c.role == "value"]
    assert periods == ["2025", "2024", "2023"]

    # Check extracted values match ground truth
    labels = [r.label.lower() for r in table.rows]
    assert any("revenue" in l for l in labels)
    assert any("cost of sales" in l for l in labels)
    assert any("gross profit" in l for l in labels)
    assert any("net income" in l for l in labels)

    rev_row = next(r for r in table.rows if "revenue" in r.label.lower())
    assert rev_row.cells[1].value == SCANNED_INCOME_METRICS["Revenue"]["2025"]
    assert rev_row.cells[2].value == SCANNED_INCOME_METRICS["Revenue"]["2024"]
    assert rev_row.cells[3].value == SCANNED_INCOME_METRICS["Revenue"]["2023"]

    cost_row = next(r for r in table.rows if "cost of sales" in r.label.lower())
    assert cost_row.cells[1].value == SCANNED_INCOME_METRICS["Cost of Sales"]["2025"]

    gp_row = next(r for r in table.rows if "gross profit" in r.label.lower())
    assert gp_row.cells[1].value == SCANNED_INCOME_METRICS["Gross Profit"]["2025"]


def test_scanned_balance_sheet_reconstruction(tmp_path) -> None:
    pdf_path = create_scanned_balance_sheet_pdf(tmp_path / "balance.pdf")
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "balance.pdf")
    page = result.pages[0]

    assert page.metadata["ocr_applied"] is True
    tables_data = page.metadata.get("financial_tables", [])
    assert len(tables_data) == 1
    table = FinancialTable.model_validate(tables_data[0])

    assert table.status == "certain"
    value_cols = [c for c in table.columns if c.role == "value"]
    assert value_cols[0].period == "2025"

    labels = {r.label.lower(): r for r in table.rows}
    assert any("total assets" in l for l in labels)
    assets_row = next(r for l, r in labels.items() if "total assets" in l)
    assert assets_row.cells[1].value == SCANNED_BALANCE_METRICS["Total assets"]["2025"]


def test_scanned_cash_flow_negative_values_preservation(tmp_path) -> None:
    pdf_path = create_scanned_cash_flow_pdf(tmp_path / "cash_flow.pdf")
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "cash_flow.pdf")
    page = result.pages[0]

    tables_data = page.metadata.get("financial_tables", [])
    assert len(tables_data) == 1
    table = FinancialTable.model_validate(tables_data[0])

    labels = {r.label.lower(): r for r in table.rows}
    inv_row = next(r for l, r in labels.items() if "investing cash flow" in l)
    assert inv_row.cells[1].value == Decimal("-90000000")


def test_scanned_table_accounting_conflict_sets_uncertainty(tmp_path) -> None:
    # Introduce conflict where Gross Profit does not equal Revenue - Cost of Sales
    pdf_path = create_scanned_income_statement_pdf(
        tmp_path / "conflict.pdf", introduce_conflict=True
    )
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "conflict.pdf")
    page = result.pages[0]

    tables_data = page.metadata.get("financial_tables", [])
    assert len(tables_data) == 1
    table = FinancialTable.model_validate(tables_data[0])

    assert table.status == "uncertain"
    assert any("reconciliation_conflict" in w for w in table.warnings)


def test_rotated_scanned_page_extraction(tmp_path) -> None:
    pdf_path = create_scanned_income_statement_pdf(
        tmp_path / "rotated.pdf", rotation=90
    )
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "rotated.pdf")
    page = result.pages[0]

    assert page.metadata["ocr_applied"] is True
    assert "normalized_rotation_90deg" in page.metadata["ocr_preprocessing"]


def test_mixed_digital_and_scanned_pdf_extraction(tmp_path) -> None:
    pdf_path = create_mixed_digital_scanned_pdf(tmp_path / "mixed.pdf")
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "mixed.pdf")
    assert result.page_count == 2

    # Page 1 must be digital without OCR overhead
    p1 = result.pages[0]
    assert p1.metadata["page_mode"] == "digital_text"
    assert p1.metadata["ocr_applied"] is False
    assert "Apex Global Technologies" in p1.extracted_text

    # Page 2 must be OCR-processed
    p2 = result.pages[1]
    assert p2.metadata["ocr_applied"] is True
    assert len(p2.metadata["financial_tables"]) == 1


def test_text_chunking_with_scanned_tables(tmp_path) -> None:
    pdf_path = create_scanned_income_statement_pdf(tmp_path / "income_chunk.pdf")
    document_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "income_chunk.pdf")
    units = _page_units(result.pages, target_size=500, overlap_size=100)

    assert len(units) >= 1
    table_units = [u for u in units if u.is_table]
    assert len(table_units) >= 1
    assert "[FINASSIST_TABLE_V1]" in table_units[0].text
    assert "Consolidated Statements of Income" in table_units[0].text


def test_deterministic_calculation_with_scanned_table(tmp_path) -> None:
    pdf_path = create_scanned_income_statement_pdf(tmp_path / "income_calc.pdf")
    document_id = uuid4()
    user_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "income_calc.pdf")
    units = _page_units(result.pages, target_size=500, overlap_size=100)
    table_unit = next(u for u in units if u.is_table)

    evidence = [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="income_calc.pdf",
            page_numbers=[1],
            chunk_text=table_unit.text,
            similarity_score=0.95,
        )
    ]

    # 1. Gross Profit Margin FY2025: 420,000 / 1,200,000 = 35.00%
    proof_gm = calculate("Calculate gross profit margin in FY2025", evidence)
    assert proof_gm is not None
    assert "35.00%" in proof_gm.answer

    # 2. Revenue growth FY2024 to FY2025: (1,200,000 - 950,000) / 950,000 * 100 = 26.32%
    proof_growth = calculate("Calculate revenue growth from FY2024 to FY2025", evidence)
    assert proof_growth is not None
    assert "26.32%" in proof_growth.answer


def test_unsupported_period_abstention_on_scanned_table(tmp_path) -> None:
    pdf_path = create_scanned_income_statement_pdf(tmp_path / "income_abstain.pdf")
    document_id = uuid4()
    user_id = uuid4()

    result = extract_pdf_pages(pdf_path, document_id, "income_abstain.pdf")
    units = _page_units(result.pages, target_size=500, overlap_size=100)
    table_unit = next(u for u in units if u.is_table)

    evidence = [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=user_id,
            document_id=document_id,
            filename="income_abstain.pdf",
            page_numbers=[1],
            chunk_text=table_unit.text,
            similarity_score=0.95,
        )
    ]

    # Requesting FY2022 which is not in the FY2023-FY2025 table
    proof = calculate("Calculate gross profit margin in FY2022", evidence)
    # Must abstain without guessing
    assert proof is None
