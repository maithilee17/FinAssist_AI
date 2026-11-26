"""Bounded PyMuPDF financial tables with explicit column/period provenance."""

import hashlib
import json
import re
from decimal import Decimal
from time import perf_counter
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from app.services.financial_cell_normalizer import (
    FinancialCell,
    financial_context,
    normalize_financial_cell,
)
from app.services.query_analyzer import extract_company_names

TABLE_MARKER = "[FINASSIST_TABLE_V1]\n"
MAX_TABLES = 32
MAX_ROWS = 2000
MAX_COLUMNS = 16
MAX_CELLS = 10000


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    header_path: list[str]
    period: str | None = None
    reporting_date: str | None = None
    period_kind: Literal["duration", "instant", "unspecified"] = "unspecified"
    frequency: str = "unspecified"
    consolidation: str = "unspecified"
    basis: str = "reported"
    entity: str | None = None
    role: Literal["label", "value", "reference"] = "value"
    currency: str | None = None
    multiplier: Decimal = Decimal(1)
    warnings: list[str] = Field(default_factory=list)


class TableRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    label: str
    cells: list[FinancialCell]
    kind: str = "data"
    indent: float = 0
    section_path: list[str] = Field(default_factory=list)


class FinancialTable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    table_id: UUID
    document_id: UUID
    page_number: int = Field(ge=1)
    bbox: tuple[float, float, float, float]
    title: str
    entity_context: str
    row_count: int
    column_count: int
    header_rows: list[list[str | None]]
    columns: list[TableColumn]
    rows: list[TableRow]
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["certain", "uncertain"] = "certain"
    method: str = "PyMuPDF.find_tables/lines"
    continuation_of: UUID | None = None


def _period_header(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:Q[1-4]\s*)?(?:FY\s*)?(?:19|20)\d{2}(?:\s+(?:actual|annual|budget|forecast))?",
            value.strip(),
            re.IGNORECASE,
        )
        or re.search(r"\b(?:19|20)\d{2}\b", value)
        and not re.search(r"[,.$%]", value)
    )


def _scope(text: str) -> tuple[str, str, str]:
    quarterly = re.search(r"\bQ([1-4])\b", text, re.IGNORECASE)
    frequency = (
        f"quarterly:Q{quarterly.group(1)}"
        if quarterly
        else (
            "half-year"
            if re.search(r"six months|half.year", text, re.IGNORECASE)
            else "annual"
            if re.search(r"\bFY\s*\d{4}|annual|year ended", text, re.IGNORECASE)
            else "unspecified"
        )
    )
    scopes = [
        s
        for s in ("consolidated", "standalone")
        if re.search(rf"\b{s}\b", text, re.IGNORECASE)
    ]
    scope = scopes[0] if len(scopes) == 1 else "ambiguous" if scopes else "unspecified"
    bases = [
        b
        for b in ("actual", "budget", "forecast")
        if re.search(rf"\b{b}\b", text, re.IGNORECASE)
    ]
    basis = bases[0] if len(bases) == 1 else "ambiguous" if bases else "reported"
    return frequency, scope, basis


def _normalize_table(
    source,
    document_id: UUID,
    page_number: int,
    context: str,
    entity_context: str,
    notes: list[str],
    words,
) -> FinancialTable:
    raw = source.extract()
    if (
        not raw
        or len(raw) > MAX_ROWS
        or len(raw[0]) > MAX_COLUMNS
        or len(raw) * len(raw[0]) > MAX_CELLS
    ):
        raise ValueError("table_resource_limit")
    count = len(raw[0])
    if count < 2 or any(len(row) != count for row in raw):
        raise ValueError("inconsistent_table_dimensions")
    start = next(
        (
            index
            for index, row in enumerate(raw)
            if row[0]
            and any(
                value
                and not _period_header(value)
                and normalize_financial_cell(value).value is not None
                for value in row[1:]
            )
        ),
        len(raw),
    )
    headers = raw[:start]
    if not headers and getattr(source.header, "external", False):
        headers = [list(source.header.names)]
    paths: list[list[str]] = [[] for _ in range(count)]
    for index, header in enumerate(headers):
        for col, text in enumerate(header):
            if text:
                value = " ".join(text.split())
                paths[col].append(value)
                # Propagate only a geometrically merged header, never a blank
                # data cell. PyMuPDF gives the spanning rectangle in this row.
                if index < len(source.rows):
                    rect = source.rows[index].cells[col]
                    if rect:
                        for following in range(col + 1, count):
                            next_rect = next(
                                (
                                    r.cells[following]
                                    for r in source.rows
                                    if r.cells[following]
                                ),
                                None,
                            )
                            if (
                                next_rect
                                and rect[0] <= next_rect[0]
                                and rect[2] >= next_rect[2]
                                and not header[following]
                            ):
                                paths[following].append(value)
    currency, multiplier, warnings = financial_context(context)
    frequency, consolidation, basis = _scope(context)
    title = next(
        (
            line
            for line in reversed(context.splitlines())
            if re.search(
                r"income statement|cash flow statement|balance sheet|statement of (?:income|cash|financial)|consolidated.*statement",
                line,
                re.IGNORECASE,
            )
        ),
        "Financial table",
    )
    columns = []
    context_years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", context))
    for col, path in enumerate(paths):
        header = " ".join(path)
        header_entities = extract_company_names(header)
        years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", header))
        period = (
            next(iter(years))
            if len(years) == 1
            else next(iter(context_years))
            if not years and len(context_years) == 1
            else None
        )
        own_currency, own_multiplier, own_warnings = financial_context(header)
        own_frequency, own_scope, own_basis = _scope(header)
        kind = (
            "instant"
            if re.search(r"balance sheet|financial position", title, re.IGNORECASE)
            or any(
                re.fullmatch(
                    r"assets|liabilities and equity", h[0] or "", re.IGNORECASE
                )
                for h in headers
                if h
            )
            else "duration"
            if re.search(r"income|cash flow", title, re.IGNORECASE)
            else "unspecified"
        )
        role = (
            "label"
            if col == 0
            else "reference"
            if re.fullmatch(
                r"notes?|references?|sources?", header.strip(), re.IGNORECASE
            )
            else "value"
        )
        columns.append(
            TableColumn(
                index=col,
                header_path=path,
                period=period,
                entity=header_entities[0] if len(header_entities) == 1 else None,
                reporting_date=(
                    re.search(
                        r"\b\d{1,2}\s+[A-Za-z]+\s+(?:19|20)\d{2}\b", header
                    ).group()
                    if kind == "instant"
                    and re.search(r"\b\d{1,2}\s+[A-Za-z]+\s+(?:19|20)\d{2}\b", header)
                    else None
                ),
                period_kind=kind,
                frequency="instant"
                if kind == "instant"
                else own_frequency
                if own_frequency != "unspecified"
                else frequency,
                consolidation=own_scope
                if own_scope != "unspecified"
                else consolidation,
                basis=own_basis if own_basis != "reported" else basis,
                role=role,
                currency=own_currency or currency,
                multiplier=own_multiplier if own_multiplier != 1 else multiplier,
                warnings=own_warnings
                + (["ambiguous_period_header"] if len(years) > 1 else []),
            )
        )
    status = "certain"
    value_columns = [c for c in columns if c.role == "value"]
    if any(c.entity for c in value_columns):
        warnings.append("column_entity_requires_review")
        status = "uncertain"
    signatures = [
        (c.period, c.frequency, c.consolidation, c.basis, c.entity)
        for c in value_columns
    ]
    if not headers or start == len(raw) or len(set(signatures)) != len(signatures):
        warnings.append("ambiguous_header_alignment")
        status = "uncertain"
    if (
        any(
            c.warnings or c.consolidation == "ambiguous" or c.basis == "ambiguous"
            for c in value_columns
        )
        or warnings
    ):
        status = "uncertain"
    dash_zero = bool(
        re.search(
            r"dash(?:es)? (?:denotes?|means?|represents?) zero",
            context + " ".join(notes),
            re.IGNORECASE,
        )
    )
    rows = []
    section = []
    for index, raw_row in enumerate(raw[start:], start):
        label = " ".join((raw_row[0] or "").split())
        cells = [
            normalize_financial_cell(
                value,
                currency=columns[col].currency,
                multiplier=columns[col].multiplier,
                dash_is_zero=dash_zero,
            )
            for col, value in enumerate(raw_row)
        ]
        kind = (
            "data"
            if any(
                cell.value is not None or cell.kind == "ambiguous" for cell in cells[1:]
            )
            else "section"
        )
        if (
            all(not value or _period_header(value) for value in raw_row[1:])
            and any(raw_row[1:])
            and label == " ".join((headers[-1][0] or "").split())
        ):
            kind = "repeated_header"
        if label and kind == "section":
            section = [label]
        if label and re.search(r"^total\b|profit$", label, re.IGNORECASE):
            kind = "subtotal"
        if any(c.role == "reference" and cells[c.index].raw for c in columns):
            for col in value_columns:
                cells[col.index].warnings.append("row_reference_requires_review")
        rect = source.rows[index].cells[0] if index < len(source.rows) else None
        positions = [
            w[0]
            for w in words
            if rect
            and rect[0] <= (w[0] + w[2]) / 2 <= rect[2]
            and rect[1] <= (w[1] + w[3]) / 2 <= rect[3]
        ]
        indent = round(max(0, min(positions) - rect[0]), 2) if positions and rect else 0
        rows.append(
            TableRow(
                index=index,
                label=label,
                cells=cells,
                kind=kind,
                indent=indent,
                section_path=section,
            )
        )
    bbox = tuple(round(float(v), 3) for v in source.bbox)
    identity = json.dumps(
        [page_number, bbox, raw], ensure_ascii=False, separators=(",", ":")
    )
    table_id = uuid5(
        NAMESPACE_URL,
        f"finassist:table:{document_id}:{hashlib.sha256(identity.encode()).hexdigest()}",
    )
    return FinancialTable(
        table_id=table_id,
        document_id=document_id,
        page_number=page_number,
        bbox=bbox,
        title=title,
        entity_context=entity_context + "\n" + context,
        row_count=len(raw),
        column_count=count,
        header_rows=headers,
        columns=columns,
        rows=rows,
        notes=notes,
        warnings=warnings,
        status=status,
    )


def extract_financial_tables(
    page, document_id: UUID, page_number: int, document_title: str = ""
) -> tuple[list[FinancialTable], list[str], dict[str, float]]:
    start = perf_counter()
    warnings = []
    if not hasattr(page, "find_tables"):
        return [], ["table_detection_unavailable_text_fallback"], {}
    if page.rect.width * page.rect.height > 50_000_000:
        return [], ["page_layout_resource_limit_text_fallback"], {}
    try:
        if len(page.get_drawings()) > 10000:
            return [], ["page_drawing_resource_limit_text_fallback"], {}
        finder = page.find_tables(strategy="lines")
        candidates = finder.tables
    except Exception:  # noqa: BLE001 - individual-page detector failures must preserve readable text
        return [], ["table_detection_failed_text_fallback"], {}
    detected = perf_counter()
    tables = []
    blocks = page.get_text("blocks", sort=True)
    words = page.get_text("words", sort=True)
    for source in candidates[:MAX_TABLES]:
        bbox = source.bbox
        preceding = [
            str(b[4]).strip()
            for b in blocks
            if b[3] <= bbox[1] + 1 and bbox[1] - b[3] < 130
        ]
        context = "\n".join(preceding[-4:])
        notes = [
            str(b[4]).strip()
            for b in blocks
            if bbox[3] <= b[1] <= bbox[3] + 65
            and re.search(
                r"^\s*[*†‡]|\b(?:note|unaudited|restated|dash)\b",
                str(b[4]),
                re.IGNORECASE,
            )
        ]
        try:
            tables.append(
                _normalize_table(
                    source,
                    document_id,
                    page_number,
                    context,
                    document_title,
                    notes,
                    words,
                )
            )
        except (ValueError, IndexError, TypeError, AttributeError):
            warnings.append("table_normalization_failed_text_fallback")
    if len(candidates) > MAX_TABLES:
        warnings.append("table_count_limit_text_fallback")
    end = perf_counter()
    return (
        tables,
        warnings,
        {
            "detection_ms": round((detected - start) * 1000, 3),
            "normalization_ms": round((end - detected) * 1000, 3),
        },
    )


def narrative_outside_tables(page, tables: list[FinancialTable]) -> str:
    lines = {}
    for word in page.get_text("words", sort=True):
        if any(
            pymupdf.Rect(table.bbox).contains(
                pymupdf.Point((word[0] + word[2]) / 2, (word[1] + word[3]) / 2)
            )
            for table in tables
        ):
            continue
        lines.setdefault((word[5], word[6]), []).append(word[4])
    return "\n\n".join(" ".join(words) for words in lines.values())


def decode_table_chunk(text: str) -> FinancialTable | None:
    if not text.startswith(TABLE_MARKER) or len(text) > 100_000:
        return None
    try:
        value = json.loads(text[len(TABLE_MARKER) :])
        defaults = value.pop("column_defaults", {})
        for column in value["columns"]:
            for name, default in defaults.items():
                column.setdefault(name, default)
        for row in value["rows"]:
            for index, cell in enumerate(row["cells"]):
                column = value["columns"][index]
                if index == 0:
                    cell.setdefault("raw", row["label"])
                elif cell.get("kind") == "number":
                    cell.setdefault("currency", column.get("currency"))
                    cell.setdefault("multiplier", column.get("multiplier", "1"))
        table = FinancialTable.model_validate(value)
        if (
            table.version != 1
            or not 2 <= table.column_count <= MAX_COLUMNS
            or len(table.rows) > MAX_ROWS
        ):
            return None
        if len(table.columns) != table.column_count or any(
            len(r.cells) != table.column_count for r in table.rows
        ):
            return None
        if any(c.index != i or c.multiplier <= 0 for i, c in enumerate(table.columns)):
            return None
        return table
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def encode_table_chunk(table: FinancialTable) -> str:
    """Avoid repeating column currency/units in every cell's embedding text.

    Normalized values are already base units. Decoding restores provenance only,
    never applies a second multiplier. Full raw geometry stays in page metadata.
    """
    value = table.model_dump(
        mode="json",
        exclude_defaults=True,
        exclude_none=True,
        exclude={"rows": {"__all__": {"indent"}}},
    )
    value["header_rows"] = []  # header paths already preserve all essential levels
    value["entity_context"] = table.entity_context.splitlines()[0]
    common = {}
    for name in (
        "currency",
        "multiplier",
        "frequency",
        "consolidation",
        "basis",
        "period_kind",
    ):
        values = [column.get(name) for column in value["columns"]]
        if values and values[0] is not None and all(v == values[0] for v in values):
            common[name] = values[0]
            for column in value["columns"]:
                column.pop(name, None)
    if common:
        value["column_defaults"] = common
    for row, original in zip(value["rows"], table.rows, strict=True):
        for index, cell in enumerate(row["cells"]):
            column = table.columns[index]
            if index == 0 and original.cells[0].raw == original.label:
                cell.pop("raw", None)
                cell.pop("currency", None)
                cell.pop("multiplier", None)
            if index > 0:
                if original.cells[index].currency == column.currency:
                    cell.pop("currency", None)
                if original.cells[index].multiplier == column.multiplier:
                    cell.pop("multiplier", None)
    return TABLE_MARKER + json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_table(table: FinancialTable) -> str:
    headers = [" / ".join(c.header_path) for c in table.columns]
    context = f"{table.title}\n{table.entity_context}\n"
    units = "; ".join(
        f"{c.period or 'unspecified period'}: {c.currency or 'unspecified currency'}, multiplier {c.multiplier}, {c.frequency}, {c.consolidation}, {c.basis}"
        for c in table.columns[1:]
        if c.role == "value"
    )
    rows = [" | ".join(headers)] + [
        " | ".join(cell.raw or "[missing]" for cell in row.cells) for row in table.rows
    ]
    return (
        context
        + units
        + "\n"
        + "\n".join(rows)
        + "\n"
        + "\n".join(table.notes + table.warnings)
    )


def table_evidence_text(text: str) -> str:
    """Expose financial rows, not numeric JSON identifiers/geometry, to the LLM."""
    if not text.startswith(TABLE_MARKER):
        return text
    table = decode_table_chunk(text)
    return (
        render_table(table)
        if table
        else "Uncertain structured table: no verified values."
    )
