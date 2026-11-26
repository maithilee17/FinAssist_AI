"""Comprehensive test suite for the Financial Analytics Dashboard service and API."""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.document import Document, DocumentPage, DocumentStatus
from app.models.user import User
from app.schemas.dashboard import FinancialDashboardResponse
from app.services.financial_dashboard import (
    _format_currency_compact,
    _format_currency_full,
    _format_percentage,
    build_financial_dashboard,
)


def _make_table_metadata(
    year_data: dict[str, dict[str, int]],
    currency: str = "USD",
    multiplier: int = 1,
    status: str = "certain",
    warnings: list[str] | None = None,
    company: str = "Example Industries Inc.",
) -> dict:
    years = sorted(year_data.keys())
    columns = [
        {"index": 0, "header_path": ["Financial Metric"], "role": "label"}
    ]
    for idx, yr in enumerate(years, 1):
        columns.append({
            "index": idx,
            "header_path": [f"FY{yr}"],
            "period": yr,
            "role": "value",
            "currency": currency,
            "multiplier": multiplier,
        })

    metric_labels = [
        ("Revenue", "revenue"),
        ("Cost of Sales", "cost_of_sales"),
        ("Gross Profit", "gross_profit"),
        ("Operating Income", "operating_income"),
        ("Net Income", "net_income"),
    ]

    rows = []
    for row_idx, (display_label, key) in enumerate(metric_labels):
        cells = [{"raw": display_label, "value": None, "kind": "text"}]
        for yr in years:
            val = year_data[yr].get(key)
            if val is not None:
                cells.append({
                    "raw": f"{val:,}",
                    "value": val * multiplier,
                    "currency": currency,
                    "multiplier": multiplier,
                    "kind": "number",
                })
            else:
                cells.append({"raw": "", "value": None, "kind": "missing"})
        rows.append({"index": row_idx, "label": display_label, "cells": cells, "kind": "data"})

    return {
        "status": status,
        "title": "Consolidated Statements of Income",
        "entity_context": f"{company}\nAnnual report",
        "columns": columns,
        "rows": rows,
        "warnings": warnings or [],
    }


def test_format_helpers():
    assert _format_currency_compact(Decimal("1200000"), "USD") == "$1.20M"
    assert _format_currency_compact(Decimal("420000"), "USD") == "$420K"
    assert _format_currency_compact(Decimal("91000"), "USD") == "$91K"
    assert _format_currency_compact(Decimal("1500000000"), "USD") == "$1.50B"
    assert _format_currency_compact(Decimal("500"), "USD") == "$500.00"
    assert _format_percentage(Decimal("35.00")) == "35.00%"
    assert _format_percentage(Decimal("7.58")) == "7.58%"


def test_multi_year_financial_metrics_and_ratios():
    """Verify three-year fixture values match known baseline calculations."""
    doc_id = uuid4()
    # Three-year synthetic fixture values
    year_data = {
        "2023": {"revenue": 820000, "cost_of_sales": 560000, "gross_profit": 260000, "operating_income": 100000, "net_income": 65000},
        "2024": {"revenue": 950000, "cost_of_sales": 630000, "gross_profit": 320000, "operating_income": 130000, "net_income": 78000},
        "2025": {"revenue": 1200000, "cost_of_sales": 780000, "gross_profit": 420000, "operating_income": 160000, "net_income": 91000},
    }
    table_meta = _make_table_metadata(year_data)
    pages_data = [{"page_number": 1, "extraction_metadata": {"financial_tables": [table_meta]}}]

    res = build_financial_dashboard(doc_id, "three_year.pdf", pages_data)

    assert res.has_financial_data is True
    assert res.available_years == ["2023", "2024", "2025"]  # Chronological order
    assert res.company_name == "Example Industries Inc."
    assert res.currency == "USD"

    # KPI Cards (Latest Year = FY2025)
    cards = {c.label: c for c in res.kpi_cards}
    assert cards["Total Revenue"].value == 1200000.0
    assert cards["Total Revenue"].formatted_value == "$1.20M"
    assert cards["Total Revenue"].period == "FY2025"
    assert cards["Total Revenue"].yoy_change == 26.32  # (1200000 - 950000) / 950000 * 100 = 26.32%

    assert cards["Gross Profit"].value == 420000.0
    assert cards["Gross Profit"].formatted_value == "$420K"
    assert cards["Gross Profit"].yoy_change == 31.25  # (420000 - 320000) / 320000 * 100 = 31.25%

    assert cards["Gross Margin"].value == 35.00  # 420,000 / 1,200,000 * 100 = 35.00%
    assert cards["Gross Margin"].formatted_value == "35.00%"
    assert cards["Gross Margin"].yoy_change == 1.32  # 35.00% - 33.68% = +1.32 percentage points (pp)
    assert cards["Gross Margin"].yoy_change_formatted == "+1.32 pp"
    assert cards["Gross Margin"].yoy_change_unit == "pp"

    assert cards["Net Income"].value == 91000.0
    assert cards["Net Income"].formatted_value == "$91K"
    assert cards["Net Income"].yoy_change == 16.67  # (91000 - 78000) / 78000 * 100 = 16.67%

    assert cards["Operating Income"].value == 160000.0
    assert cards["Operating Income"].formatted_value == "$160K"

    # Verify Margins Trend
    margins = {m.period: m for m in res.margin_trend}
    assert margins["2023"].gross_profit_margin == 31.71  # 260000 / 820000 = 31.71%
    assert margins["2023"].net_profit_margin == 7.93      # 65000 / 820000 = 7.93%
    assert margins["2024"].gross_profit_margin == 33.68  # 320000 / 950000 = 33.68%
    assert margins["2024"].net_profit_margin == 8.21      # 78000 / 950000 = 8.21%
    assert margins["2025"].gross_profit_margin == 35.00  # 420000 / 1200000 = 35.00%
    assert margins["2025"].net_profit_margin == 7.58      # 91000 / 1200000 = 7.58%

    # Summary
    assert res.summary is not None
    assert "26.32%" in res.summary.growth
    assert "expanded steadily" in res.summary.key_observations[0].lower()
    assert len(res.summary.citations) >= 1


def test_single_year_report_withholds_multi_year_growth():
    """Verify single-year financial report displays metrics without fabricating trends."""
    doc_id = uuid4()
    year_data = {
        "2025": {"revenue": 500000, "cost_of_sales": 300000, "gross_profit": 200000, "net_income": 45000}
    }
    table_meta = _make_table_metadata(year_data, company="Northstar Components")
    pages_data = [{"page_number": 1, "extraction_metadata": {"financial_tables": [table_meta]}}]

    res = build_financial_dashboard(doc_id, "single_year.pdf", pages_data)

    assert res.has_financial_data is True
    assert res.available_years == ["2025"]
    cards = {c.label: c for c in res.kpi_cards}
    assert cards["Total Revenue"].value == 500000.0
    assert cards["Total Revenue"].yoy_change is None  # Must NOT invent YoY change
    assert cards["Gross Margin"].value == 40.00       # 200,000 / 500,000 = 40.00%

    assert res.summary is not None
    assert any("single reporting period" in lim.lower() for lim in res.summary.limitations)


def test_missing_data_and_zero_denominator_safeguards():
    """Verify missing values display unavailable state and zero revenue avoids division by zero."""
    doc_id = uuid4()
    year_data = {
        "2024": {"revenue": 0, "net_income": 0},
        "2025": {"revenue": 100000},  # Missing gross profit and net income
    }
    table_meta = _make_table_metadata(year_data)
    pages_data = [{"page_number": 1, "extraction_metadata": {"financial_tables": [table_meta]}}]

    res = build_financial_dashboard(doc_id, "sparse.pdf", pages_data)

    assert res.has_financial_data is True
    cards = {c.label: c for c in res.kpi_cards}
    assert cards["Gross Profit"].value is None
    assert cards["Gross Profit"].formatted_value == "Not available"
    assert cards["Net Income"].value is None
    assert cards["Net Income"].formatted_value == "Not available"


def test_ocr_uncertainty_safeguard():
    """Verify uncertain OCR status surfaces warnings and limitation notes."""
    doc_id = uuid4()
    year_data = {
        "2025": {"revenue": 100000, "gross_profit": 40000, "net_income": 10000}
    }
    table_meta = _make_table_metadata(
        year_data,
        status="uncertain",
        warnings=["ocr_character_substitution_detected", "ocr_accounting_reconciliation_conflict_col_1"],
    )
    pages_data = [{"page_number": 1, "extraction_metadata": {"financial_tables": [table_meta]}}]

    res = build_financial_dashboard(doc_id, "uncertain_scan.pdf", pages_data)

    assert res.has_financial_data is True
    assert len(res.warnings) >= 1
    assert any("uncertain" in w.lower() for w in res.warnings)
    assert res.summary is not None
    assert any("ocr" in lim.lower() or "warning" in lim.lower() for lim in res.summary.limitations)


def test_empty_document_without_financial_tables():
    """Verify clean empty state when document has no tabular financial data."""
    doc_id = uuid4()
    pages_data = [{"page_number": 1, "extraction_metadata": {"financial_tables": []}}]

    res = build_financial_dashboard(doc_id, "narrative.pdf", pages_data)

    assert res.has_financial_data is False
    assert res.available_years == []
    assert res.kpi_cards == []


def test_percentage_points_vs_relative_percentage_growth():
    """Verify strict financial distinction between percentage points (pp) and relative growth (%)."""
    doc_id = uuid4()
    # Scenario A: Expansion (33.68% -> 35.00% = +1.32 pp)
    year_data_expand = {
        "2024": {"revenue": 950000, "cost_of_sales": 630000, "gross_profit": 320000, "net_income": 78000},
        "2025": {"revenue": 1200000, "cost_of_sales": 780000, "gross_profit": 420000, "net_income": 91000},
    }
    table_expand = _make_table_metadata(year_data_expand)
    res_expand = build_financial_dashboard(doc_id, "expand.pdf", [{"page_number": 1, "extraction_metadata": {"financial_tables": [table_expand]}}])
    cards_expand = {c.label: c for c in res_expand.kpi_cards}

    # Gross Margin must be percentage points
    assert cards_expand["Gross Margin"].value == 35.00
    assert cards_expand["Gross Margin"].yoy_change == 1.32
    assert cards_expand["Gross Margin"].yoy_change_unit == "pp"
    assert cards_expand["Gross Margin"].yoy_change_formatted == "+1.32 pp"

    # Revenue must be relative percentage
    assert cards_expand["Total Revenue"].value == 1200000.0
    assert cards_expand["Total Revenue"].yoy_change == 26.32
    assert cards_expand["Total Revenue"].yoy_change_unit == "%"
    assert cards_expand["Total Revenue"].yoy_change_formatted == "+26.32%"

    # Scenario B: Contraction (35.00% -> 30.00% = -5.00 pp)
    year_data_contract = {
        "2024": {"revenue": 1000000, "cost_of_sales": 650000, "gross_profit": 350000, "net_income": 80000},
        "2025": {"revenue": 1000000, "cost_of_sales": 700000, "gross_profit": 300000, "net_income": 50000},
    }
    table_contract = _make_table_metadata(year_data_contract)
    res_contract = build_financial_dashboard(doc_id, "contract.pdf", [{"page_number": 1, "extraction_metadata": {"financial_tables": [table_contract]}}])
    cards_contract = {c.label: c for c in res_contract.kpi_cards}

    assert cards_contract["Gross Margin"].value == 30.00
    assert cards_contract["Gross Margin"].yoy_change == -5.00
    assert cards_contract["Gross Margin"].yoy_change_unit == "pp"
    assert cards_contract["Gross Margin"].yoy_change_formatted == "-5.00 pp"

    # Revenue flat (0.00%)
    assert cards_contract["Total Revenue"].yoy_change == 0.00
    assert cards_contract["Total Revenue"].yoy_change_formatted == "+0.00%"


def test_end_to_end_real_three_year_pdf_extraction_to_dashboard(tmp_path):
    """Verify full end-to-end extraction from actual three_year.pdf fixture to dashboard."""
    from app.services.pdf_processor import extract_pdf_pages
    from tests.table_fixtures import make_fixture

    pdf_path = tmp_path / "three_year.pdf"
    make_fixture(pdf_path, "three_year")
    doc_id = uuid4()

    extract_result = extract_pdf_pages(pdf_path, doc_id, "three_year.pdf")
    pages_data = [
        {"page_number": p.page_number, "extraction_metadata": p.metadata}
        for p in extract_result.pages
    ]

    res = build_financial_dashboard(doc_id, "three_year.pdf", pages_data)

    assert res.has_financial_data is True
    assert res.available_years == ["2023", "2024", "2025"]
    assert res.company_name == "Example Industries"

    # Verify KPI metrics match known synthetic values
    cards = {c.label: c for c in res.kpi_cards}
    assert cards["Total Revenue"].value == 1200000.0
    assert cards["Gross Profit"].value == 420000.0
    assert cards["Gross Margin"].value == 35.00
    assert cards["Net Income"].value == 91000.0
    assert cards["Total Revenue"].yoy_change == 26.32

    # Verify Margins across years
    margins = {m.period: m for m in res.margin_trend}
    assert margins["2023"].gross_profit_margin == 31.71
    assert margins["2024"].gross_profit_margin == 33.68
    assert margins["2025"].gross_profit_margin == 35.00
    assert margins["2023"].net_profit_margin == 7.93
    assert margins["2024"].net_profit_margin == 8.21
    assert margins["2025"].net_profit_margin == 7.58

    # Verify Revenue trend
    rev_trend = {r.period: r.revenue for r in res.revenue_trend}
    assert rev_trend == {"2023": 820000.0, "2024": 950000.0, "2025": 1200000.0}


# =========================================================================
# API Endpoint Integration & Security Tests
# =========================================================================

async def create_user_token(client: AsyncClient, email: str) -> str:
    password = "SecureDashboardUser123!"
    reg = await client.post(
        "/api/auth/register",
        json={"full_name": "Dashboard Tester", "email": email, "password": password},
    )
    assert reg.status_code == 201
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


@pytest.mark.anyio
async def test_dashboard_api_unauthorized_rejection(client):
    """Verify 401 when request has no credentials."""
    resp = await client.get(f"/api/dashboard/{uuid4()}")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_dashboard_api_document_not_found(client):
    """Verify 404 when document does not exist."""
    token = await create_user_token(client, "dash-notfound@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(f"/api/dashboard/{uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert "Document not found" in resp.json()["detail"]


@pytest.mark.anyio
async def test_dashboard_api_document_isolation(client, pdf_bytes_factory):
    """Verify User B cannot access User A's document dashboard."""
    token_a = await create_user_token(client, "user-a@example.com")
    token_b = await create_user_token(client, "user-b@example.com")

    pdf = pdf_bytes_factory(["FY2025 Revenue was $1,200,000 and Gross Profit $420,000."])
    upload_resp = await client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("report-a.pdf", pdf, "application/pdf")},
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # Owner can access
    resp_owner = await client.get(
        f"/api/dashboard/{doc_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_owner.status_code == 200
    body = resp_owner.json()
    assert body["document_id"] == doc_id
    assert body["filename"] == "report-a.pdf"

    # User B receives 404 (document isolation enforced)
    resp_other = await client.get(
        f"/api/dashboard/{doc_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_other.status_code == 404
    assert "Document not found" in resp_other.json()["detail"]
