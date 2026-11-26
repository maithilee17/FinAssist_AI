"""Real deterministic digital PDFs; expected values are fixture arithmetic, not LLM output."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from app.services.claim_verifier import ClaimOverallStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import calculate
from app.services.financial_cell_normalizer import normalize_financial_cell
from app.services.financial_table_extractor import (
    decode_table_chunk,
    encode_table_chunk,
)
from app.services.pdf_processor import extract_pdf_pages
from app.services.text_chunker import chunk_pages
from app.services.vector_store import VectorSearchResult

from tests.table_fixtures import KINDS, make_fixture


def extracted(tmp_path, kind="three_year", user=None, target_size=500):
    path = tmp_path / f"{kind}.pdf"
    make_fixture(path, kind)
    doc, user = uuid4(), user or uuid4()
    result = extract_pdf_pages(path, doc, path.name)
    chunks = chunk_pages(
        result.pages,
        document_id=doc,
        user_id=user,
        target_size=target_size,
        overlap_size=min(100, target_size - 1),
    )
    evidence = [
        VectorSearchResult(c.id, user, doc, path.name, c.page_numbers, c.text, 0.9)
        for c in chunks
    ]
    return result, chunks, evidence


@pytest.mark.parametrize(
    "raw,currency,scale,value,kind",
    [
        ("$1,200,000", "USD", 1, "1200000", "number"),
        ("(90,000)", "USD", 1, "-90000", "number"),
        ("35.00%", "USD", 1000, "35.00", "percentage"),
        ("1,250", "USD", 1000, "1250000", "number"),
        ("1,25,000", "INR", 100000, "12500000000", "number"),
        ("2 million", "EUR", 1000000, "2000000", "number"),
        ("0", "GBP", 1, "0", "number"),
        ("-", "USD", 1, None, "missing"),
        ("", "USD", 1, None, "missing"),
        ("1.200,50", "EUR", 1, None, "ambiguous"),
        ("1.250", "EUR", 1, None, "ambiguous"),
        ("1 250", "EUR", 1, None, "ambiguous"),
    ],
)
def test_cell_normalization(raw, currency, scale, value, kind):
    cell = normalize_financial_cell(raw, currency=currency, multiplier=Decimal(scale))
    assert cell.raw == raw and cell.kind == kind
    assert cell.value == (Decimal(value) if value is not None else None)


@pytest.mark.parametrize("kind", KINDS)
def test_actual_pdf_layouts(tmp_path, kind):
    result, chunks, evidence = extracted(tmp_path, kind)
    tables = [t for p in result.pages for t in p.metadata["financial_tables"]]
    assert len(tables) == (2 if kind == "multipage" else 1)
    assert all(t["status"] == "certain" for t in tables)
    assert all(c.token_count <= 500 for c in chunks)
    assert "Example Industries" in result.pages[0].extracted_text
    decoded = [decode_table_chunk(x.chunk_text) for x in evidence]
    decoded = [t for t in decoded if t]
    assert decoded
    assert all(t.document_id == result.document_id for t in decoded)
    assert all(t.page_number in {1, 2} for t in decoded)
    row_ids = [(t.table_id, r.index) for t in decoded for r in t.rows]
    assert len(row_ids) == len(set(row_ids))
    if kind in {"three_year", "merged", "units"}:
        rows = {r.label: (t, r) for t in decoded for r in t.rows}
        t, row = rows["Revenue"]
        assert [c.period for c in t.columns[1:]] == ["2025", "2024", "2023"]
        assert [c.value for c in row.cells[1:]] == [
            Decimal(1200000),
            Decimal(950000),
            Decimal(820000),
        ]
    if kind == "multipage":
        assert tables[1]["continuation_of"] == tables[0]["table_id"]


@pytest.mark.parametrize(
    "kind,question,expected",
    [
        ("three_year", "Calculate gross profit margin in FY2025", "35.00%"),
        ("three_year", "Calculate net profit margin in FY2024", "8.21%"),
        ("three_year", "Calculate operating margin in FY2023", "12.20%"),
        ("three_year", "Calculate revenue growth from FY2024 to FY2025", "26.32%"),
        ("balance", "Calculate debt-to-assets ratio in FY2025", "60.00%"),
        ("cash", "Calculate net change in cash in FY2025", "20000.00USD"),
        ("units", "What was revenue in FY2025?", "1,200,000.00 USD"),
        ("merged", "Calculate gross profit margin in FY2024", "33.68%"),
        ("three_year", "Compare revenue in FY2023 and FY2025", "820,000.00 USD"),
        (
            "three_year",
            "Provide a three-year financial table of revenue, cost of sales, and gross profit",
            "| Revenue | 820,000.00 USD | 950,000.00 USD | 1,200,000.00 USD |",
        ),
        (
            "three_year",
            "Provide a three-year financial table",
            "| Net Income | 65,000.00 USD | 78,000.00 USD | 91,000.00 USD |",
        ),
    ],
)
def test_real_pdf_calculations_and_independent_verification(
    tmp_path, kind, question, expected
):
    _, _, evidence = extracted(tmp_path, kind)
    proof = calculate(question, evidence)
    assert proof and expected in proof.answer
    assert proof.inputs and proof.sources
    import re

    assert not re.search(r"(\[Source\s+\d+\])\s+\1", proof.answer)
    for fact in proof.inputs:
        source = evidence[fact.source_number - 1]
        assert (
            fact.document_id == source.document_id and fact.chunk_id == source.chunk_id
        )
        assert "table " in fact.excerpt and "column " in fact.excerpt
    claims = ClaimVerifier().verify(proof.answer, evidence, question=question)
    assert claims.overall_status == ClaimOverallStatus.VERIFIED
    altered = ClaimVerifier().verify(
        proof.answer + " unsupported 42", evidence, question=question
    )
    assert altered.overall_status == ClaimOverallStatus.UNSUPPORTED
    decision = EvidenceVerifier().verify(
        question,
        evidence,
        user_id=evidence[0].user_id,
        allowed_document_ids={evidence[0].document_id},
    )
    assert decision.evidence_status == EvidenceStatus.SUFFICIENT


@pytest.mark.parametrize(
    "kind,question",
    [
        ("three_year", "Calculate gross profit margin in FY2022"),
        ("missing", "Calculate gross profit margin in FY2024"),
        ("footnotes", "Calculate gross profit margin in FY2025"),
        ("three_year", "What was inventory in FY2025?"),
        ("quarterly", "Calculate revenue growth from FY2024 to FY2025"),
    ],
)
def test_absent_ambiguous_qualified_or_incompatible_inputs(tmp_path, kind, question):
    _, _, evidence = extracted(tmp_path, kind)
    assert calculate(question, evidence) is None


def test_source_ownership_scope_and_conflicting_cells(tmp_path):
    _, _, evidence = extracted(tmp_path)
    question = "Calculate gross profit margin in FY2025"
    assert (
        calculate(question, [replace(x, document_id=uuid4()) for x in evidence]) is None
    )
    assert calculate(question, [replace(x, user_id=uuid4()) for x in evidence]) is None
    assert (
        calculate(question, [replace(x, page_numbers=[99]) for x in evidence]) is None
    )
    revenue = next(
        x
        for x in evidence
        if (t := decode_table_chunk(x.chunk_text)) and t.rows[0].label == "Revenue"
    )
    table = decode_table_chunk(revenue.chunk_text)
    table.rows[0].cells[1].value = Decimal(1)
    assert (
        calculate(
            question,
            evidence
            + [
                replace(revenue, chunk_id=uuid4(), chunk_text=encode_table_chunk(table))
            ],
        )
        is None
    )
    decision = EvidenceVerifier().verify(
        question,
        evidence,
        user_id=uuid4(),
        allowed_document_ids={evidence[0].document_id},
    )
    assert decision.evidence_status != EvidenceStatus.SUFFICIENT


def test_stable_chunk_and_table_ids(tmp_path):
    result, chunks, _ = extracted(tmp_path)
    again = extract_pdf_pages(
        tmp_path / "three_year.pdf", result.document_id, "three_year.pdf"
    )
    assert (
        again.pages[0].metadata["financial_tables"]
        == result.pages[0].metadata["financial_tables"]
    )
    assert chunks == chunk_pages(
        again.pages, document_id=result.document_id, user_id=chunks[0].user_id
    )


@pytest.mark.parametrize(
    "text",
    [
        "[FINASSIST_TABLE_V1]\n[]",
        "[FINASSIST_TABLE_V1]\n{}",
        "[FINASSIST_TABLE_V1]\nnull",
    ],
)
def test_malformed_structured_evidence(text):
    assert decode_table_chunk(text) is None


def immediate(coroutine):
    """Run a no-I/O test coroutine without creating a Windows socket event loop."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    raise AssertionError("Unexpected real I/O in mock unit test")


def test_bounded_table_context_expansion_and_access_control(tmp_path):
    from types import SimpleNamespace

    from app.models.document import DocumentChunk
    from app.services.financial_table_context import expand_table_context

    _, chunks, evidence = extracted(tmp_path, target_size=85)
    structured = [x for x in evidence if decode_table_chunk(x.chunk_text)]
    by_id = {c.id: c for c in chunks}
    rows = [
        (
            DocumentChunk(
                id=x.chunk_id,
                user_id=x.user_id,
                document_id=x.document_id,
                chunk_index=by_id[x.chunk_id].chunk_index,
                text=x.chunk_text,
                page_numbers=x.page_numbers,
                token_count=by_id[x.chunk_id].token_count,
            ),
            x.filename,
        )
        for x in structured
    ]

    class Database:
        async def execute(self, query):
            sql = str(query)
            assert "documents.user_id" in sql and "document_chunks.user_id" in sql
            assert "documents.id IN" in sql and "documents.processing_status" in sql
            return SimpleNamespace(all=lambda: rows)

    seed = structured[:1]
    kwargs = {"user_id": seed[0].user_id, "allowed_document_ids": [seed[0].document_id]}
    expanded = immediate(
        expand_table_context(
            Database(), "Calculate net profit margin for FY2025", seed, **kwargs
        )
    )
    assert len(expanded) == len(structured)
    assert calculate("Calculate net profit margin for FY2025", expanded)
    rows[1][0].user_id = uuid4()  # defense beyond SQL filtering
    filtered = immediate(
        expand_table_context(
            Database(), "Calculate net profit margin for FY2025", seed, **kwargs
        )
    )
    assert len(filtered) == len(structured) - 1
    rows.extend(rows * 20)
    assert (
        immediate(
            expand_table_context(
                Database(), "Calculate net profit margin for FY2025", seed, **kwargs
            )
        )
        == seed
    )


def test_cross_document_comparison_does_not_mix_inputs(tmp_path):
    _, _, first = extracted(tmp_path, target_size=85)
    folder = tmp_path / "second"
    folder.mkdir()
    _, _, second = extracted(folder, user=first[0].user_id, target_size=85)
    changed = []
    for item in second:
        table = decode_table_chunk(item.chunk_text)
        if table:
            table.entity_context = "Other Industries"
            item = replace(item, chunk_text=encode_table_chunk(table))
        changed.append(item)
    proof = calculate(
        "Compare revenue in FY2025 for the two companies", first + changed
    )
    assert (
        proof
        and "Example Industries" in proof.answer
        and "Other Industries" in proof.answer
    )
    assert len({f.document_id for f in proof.inputs}) == 2
    margins = calculate(
        "Compare gross profit margin in FY2025 for both companies", first + changed
    )
    assert margins and margins.answer.count("= 35.00%") == 2
    assert len({f.document_id for f in margins.inputs}) == 2
    # An orphaned numerator from another document cannot complete a margin.
    revenue = [
        x
        for x in first
        if (t := decode_table_chunk(x.chunk_text)) and t.rows[0].label == "Revenue"
    ]
    profits = [
        x
        for x in changed
        if (t := decode_table_chunk(x.chunk_text)) and t.rows[0].label == "Gross Profit"
    ]
    assert calculate("Compare gross profit margin in FY2025", revenue + profits) is None


def test_zero_denominator_and_raw_numeric_tampering(tmp_path):
    _, _, evidence = extracted(tmp_path)
    changed = []
    for item in evidence:
        table = decode_table_chunk(item.chunk_text)
        if table and table.rows[0].label == "Revenue":
            table.rows[0].cells[1].raw = "0"
            table.rows[0].cells[1].value = Decimal(0)
            item = replace(item, chunk_text=encode_table_chunk(table))
        changed.append(item)
    assert calculate("Calculate net profit margin in FY2025", changed) is None
    changed = []
    for item in evidence:
        table = decode_table_chunk(item.chunk_text)
        if table and table.rows[0].label == "Revenue":
            table.rows[0].cells[1].value = Decimal(999)
            item = replace(item, chunk_text=encode_table_chunk(table))
        changed.append(item)
    assert calculate("What was revenue in FY2025?", changed) is None


def test_pdf_number_wrap_and_explicit_dash_semantics():
    cell = normalize_financial_cell("$1,\n200,000", currency="USD")
    assert cell.value == Decimal(1200000) and cell.raw == "$1,\n200,000"
    assert normalize_financial_cell("-", currency="USD", dash_is_zero=True).value == 0
    assert normalize_financial_cell("$1,250").warnings == ["ambiguous_currency_symbol"]


def test_inventory_absence_requires_metric_evidence():
    source = VectorSearchResult(
        uuid4(),
        uuid4(),
        uuid4(),
        "report.pdf",
        [1],
        "FY2025 revenue USD 1,200,000 and net income USD 91,000.",
        0.9,
    )
    result = EvidenceVerifier().verify(
        "What was inventory in FY2025?",
        [source],
        user_id=source.user_id,
        allowed_document_ids={source.document_id},
    )
    assert result.evidence_status != EvidenceStatus.SUFFICIENT
    assert any("inventory" in x for x in result.missing_aspects)


def test_table_failure_falls_back_without_losing_text(tmp_path, monkeypatch):
    import pymupdf

    monkeypatch.setattr(
        pymupdf.Page,
        "find_tables",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad layout")),
    )
    result, _, _ = extracted(tmp_path)
    assert "Revenue" in result.pages[0].extracted_text
    assert result.pages[0].metadata["table_warnings"] == [
        "table_detection_failed_text_fallback"
    ]


def test_uncertain_headers_never_map_values_to_a_year(tmp_path):
    import pymupdf

    from tests.table_fixtures import page_table

    path = tmp_path / "ambiguous.pdf"
    with pymupdf.open() as pdf:
        page_table(
            pdf,
            "Income Statement",
            ["Metric", "FY2025", "FY2025"],
            [["Revenue", "100", "200"], ["Gross Profit", "10", "30"]],
        )
        pdf.save(path)
    doc, user = uuid4(), uuid4()
    result = extract_pdf_pages(path, doc, path.name)
    assert result.pages[0].metadata["financial_tables"][0]["status"] == "uncertain"
    chunks = chunk_pages(result.pages, document_id=doc, user_id=user)
    evidence = [
        VectorSearchResult(c.id, user, doc, path.name, c.page_numbers, c.text, 0.9)
        for c in chunks
    ]
    assert calculate("Calculate gross profit margin in FY2025", evidence) is None


def test_repeated_headers_and_narrative_preserved(tmp_path):
    import pymupdf

    from tests.table_fixtures import page_table

    path = tmp_path / "repeated.pdf"
    with pymupdf.open() as pdf:
        page_table(
            pdf,
            "Income Statement",
            ["Metric", "FY2025"],
            [["Revenue", "100"], ["Metric", "FY2025"], ["Gross Profit", "40"]],
        )
        pdf.save(path)
    doc, user = uuid4(), uuid4()
    result = extract_pdf_pages(path, doc, path.name)
    assert "Management commentary" in result.pages[0].metadata["narrative_text"]
    assert "Revenue" not in result.pages[0].metadata["narrative_text"]
    chunks = chunk_pages(result.pages, document_id=doc, user_id=user)
    tables = [t for c in chunks if (t := decode_table_chunk(c.text))]
    assert [r.label for t in tables for r in t.rows] == ["Revenue", "Gross Profit"]


def test_unspecified_period_abstains_on_a_multi_year_calculation(tmp_path):
    _, _, evidence = extracted(tmp_path)
    assert calculate("Calculate gross profit margin", evidence) is None
    assert (
        calculate(
            "Calculate year-over-year revenue growth from FY2023 to FY2025", evidence
        )
        is None
    )


def test_small_table_is_one_logical_unit_and_composites_require_all_metrics(tmp_path):
    _, _, evidence = extracted(tmp_path)
    tables = [t for item in evidence if (t := decode_table_chunk(item.chunk_text))]
    assert len(tables) == 1 and len(tables[0].rows) == 5
    assert calculate("What were revenue and dividends in FY2025?", evidence) is None
    assert (
        calculate(
            "Calculate gross profit margin and net profit margin in FY2025", evidence
        )
        is None
    )
    result = EvidenceVerifier().verify(
        "Compare revenue in FY2024 and FY2025",
        evidence,
        user_id=evidence[0].user_id,
        allowed_document_ids={evidence[0].document_id, uuid4()},
    )
    assert result.evidence_status != EvidenceStatus.SUFFICIENT


@pytest.mark.parametrize("change", ["currency", "date", "scope"])
def test_incompatible_balance_sheet_context_abstains(tmp_path, change):
    _, _, evidence = extracted(tmp_path, "balance")
    table_source = next(x for x in evidence if decode_table_chunk(x.chunk_text))
    table = decode_table_chunk(table_source.chunk_text)
    # Put numerator and denominator in separate table groups with incompatible context.
    assets = table.model_copy(deep=True, update={"rows": [table.rows[0]]})
    liabilities = table.model_copy(deep=True, update={"rows": [table.rows[1]]})
    if change == "date":
        liabilities.columns[1].reporting_date = "30 September 2025"
    elif change == "scope":
        liabilities.columns[1].consolidation = "standalone"
    else:
        liabilities.columns[1].currency = "EUR"
        liabilities.rows[0].cells[1].currency = "EUR"
    passages = [
        replace(table_source, chunk_id=uuid4(), chunk_text=encode_table_chunk(t))
        for t in (assets, liabilities)
    ]
    assert calculate("Calculate debt-to-assets ratio in FY2025", passages) is None


def test_mixed_legacy_table_factual_comparisons_keep_existing_grounded_route(tmp_path):
    from app.services.structured_financial_calculation import table_query

    _, _, evidence = extracted(tmp_path)
    legacy = VectorSearchResult(
        uuid4(),
        evidence[0].user_id,
        uuid4(),
        "legacy.pdf",
        [1],
        "Other Industries FY2025 revenue: USD 900,000. Net income: USD 80,000.",
        0.9,
    )
    question = "Compare revenue and net income in FY2025"
    combined = evidence + [legacy]
    assert not table_query(question, combined)
    assert calculate(question, combined) is None  # no incomplete single-company proof
    decision = EvidenceVerifier().verify(
        question,
        combined,
        user_id=legacy.user_id,
        allowed_document_ids={legacy.document_id, evidence[0].document_id},
    )
    assert decision.evidence_status == EvidenceStatus.SUFFICIENT
    assert table_query("Compare gross profit margin in FY2025", combined)
