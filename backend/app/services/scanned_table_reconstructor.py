"""Reconstruct structured financial tables from OCR word bounding boxes."""

import re
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from app.services.financial_cell_normalizer import (
    FinancialCell,
    financial_context,
    normalize_financial_cell,
)
from app.services.financial_table_extractor import (
    FinancialTable,
    TableColumn,
    TableRow,
)

_YEAR_PATTERN = re.compile(
    r"\b(?:FY\s*)?(20\d{2}|19\d{2})\b", re.IGNORECASE
)
_NUMERIC_TOKEN = re.compile(
    r"^\(?\$?[€₹£¥]?\s*[\d,]+(?:\.\d+)?\)?%?$"
)
_ACCOUNTING_NEGATIVE = re.compile(
    r"^\s*[\(\[]\s*([$€₹£¥]?\s*[\d,]+(?:\.\d+)?)\s*[\)\]]\s*$"
)


def _clean_ocr_numeric_substitutions(raw: str) -> tuple[str, bool]:
    """Detect and safely clean obvious OCR character substitutions in numbers.

    Examples:
        '1,2OO,OOO' -> '1,200,000' (O -> 0)
        'l,200,000' -> '1,200,000' (l -> 1)
        'I,200,000' -> '1,200,000' (I -> 1)
        '(78O,OOO)' -> '(780,000)'
    """
    substituted = False
    cleaned = raw.strip()

    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    if is_negative:
        inner = cleaned[1:-1].strip()
    else:
        inner = cleaned

    # Check for l or I at start of number before digits or commas (e.g. l,200 or I,950)
    if re.match(r"^[€$₹£¥]?\s*[lI](?=[,\.]\d|\d)", inner):
        inner = re.sub(
            r"^[€$₹£¥]?\s*[lI]",
            lambda m: m.group(0).replace("l", "1").replace("I", "1"),
            inner,
        )
        substituted = True

    # Check for O/o substitutions in numeric strings (where there are digits/commas/currency and [Oo])
    if re.search(r"[Oo]", inner) and re.match(r"^[€$₹£¥]?\s*[\d,\.Oo]+\s*$", inner):
        if re.search(r"[\d,\.€$₹£¥]", inner):
            inner = re.sub(r"[Oo]", "0", inner)
            substituted = True

    result = f"({inner})" if is_negative else inner
    return result, substituted


def _group_words_into_lines(
    words: list[tuple[float, float, float, float, str, int, int, int]],
    y_tolerance: float = 8.0,
) -> list[dict]:
    """Group OCR words into spatial lines based on vertical midpoints."""

    if not words:
        return []

    words_sorted = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[dict] = []

    for w in words_sorted:
        y_mid = (w[1] + w[3]) / 2.0
        placed = False
        for line in lines:
            if abs(y_mid - line["y_mid"]) <= y_tolerance:
                line["words"].append(w)
                line["y_mid"] = sum(
                    (item[1] + item[3]) / 2.0 for item in line["words"]
                ) / len(line["words"])
                placed = True
                break
        if not placed:
            lines.append({"y_mid": y_mid, "words": [w]})

    lines.sort(key=lambda l: l["y_mid"])
    for line in lines:
        line["words"].sort(key=lambda w: w[0])
        line["text"] = " ".join(w[4] for w in line["words"]).strip()
        line["y0"] = min(w[1] for w in line["words"])
        line["y1"] = max(w[3] for w in line["words"])
        line["x0"] = min(w[0] for w in line["words"])
        line["x1"] = max(w[2] for w in line["words"])

    return lines


def reconstruct_scanned_financial_tables(
    words: list[tuple[float, float, float, float, str, int, int, int]],
    document_id: UUID,
    page_number: int,
    document_title: str = "",
) -> list[FinancialTable]:
    """Reconstruct typed FinancialTable instances from OCR word bounding boxes."""

    if not words:
        return []

    lines = _group_words_into_lines(words)
    if len(lines) < 3:
        return []

    # 1. Search for table header lines containing fiscal periods or column indicators
    tables: list[FinancialTable] = []
    header_indices: list[int] = []

    for idx, line in enumerate(lines):
        line_text = line["text"]
        # Skip top document headers or footers
        if idx > len(lines) - 2:
            continue

        # Ignore document titles, statement headings, date captions, notes
        is_title_or_heading = bool(
            re.search(
                r"\b(?:balance\s+sheet|income\s+statement|statements?\s+of|cash\s*flow\s+statement|annual\s+report|interim\s+report|notes\s+to|at\s+\d+|as\s+of|ended\b)\b",
                line_text,
                re.IGNORECASE,
            )
        )
        if is_title_or_heading:
            continue

        year_matches = list(_YEAR_PATTERN.finditer(line_text))
        has_amount_header = bool(
            re.search(r"\b(?:amount|usd|inr|eur|in\s+thousands|actual)\b", line_text, re.IGNORECASE)
            and re.search(r"\b(?:line\s+item|metric|item|description|particulars)\b", line_text, re.IGNORECASE)
        )

        if len(year_matches) >= 1 or has_amount_header:
            # Verify that following lines contain numeric data rows
            subsequent_numeric_lines = 0
            for next_idx in range(idx + 1, min(idx + 6, len(lines))):
                tokens = [w[4] for w in lines[next_idx]["words"]]
                if any(_NUMERIC_TOKEN.match(t) for t in tokens):
                    subsequent_numeric_lines += 1

            if subsequent_numeric_lines >= 1:
                header_indices.append(idx)

    last_consumed_line_idx = -1

    for h_idx in header_indices:
        if h_idx <= last_consumed_line_idx:
            continue

        header_line = lines[h_idx]

        # 2. Extract preceding context (title, company, currency, multiplier)
        preceding = lines[max(0, h_idx - 4) : h_idx]
        preceding_text = "\n".join(l["text"] for l in preceding)
        combined_context = (document_title + "\n" + preceding_text).strip()

        # Extract title
        title_candidates = [
            l["text"]
            for l in preceding
            if re.search(
                r"\b(?:income|balance|cash\s*flow|operations|financial|position|loss|statement)\b",
                l["text"],
                re.IGNORECASE,
            )
        ]
        table_title = title_candidates[-1] if title_candidates else "Scanned Financial Statement"

        currency, multiplier, _ = financial_context(combined_context)

        # 3. Identify Column Boundaries from Header Words
        # Partition header words into: Column 0 (Metric label) and Columns 1..N (Periods / Amounts)
        col_words = []
        for w in header_line["words"]:
            w_text = w[4]
            year_match = _YEAR_PATTERN.search(w_text)
            if year_match or re.match(r"^\(?amount|\(usd\)|\$|\(₹\)", w_text, re.IGNORECASE):
                period_str = year_match.group(1) if year_match else None
                col_words.append({
                    "word": w,
                    "x0": w[0],
                    "x1": w[2],
                    "x_center": (w[0] + w[2]) / 2.0,
                    "text": w_text,
                    "period": period_str,
                })

        if not col_words:
            # Fallback: if header line has periods but words were combined
            for w in header_line["words"]:
                if _YEAR_PATTERN.search(w[4]):
                    col_words.append({
                        "word": w,
                        "x0": w[0],
                        "x1": w[2],
                        "x_center": (w[0] + w[2]) / 2.0,
                        "text": w[4],
                        "period": _YEAR_PATTERN.search(w[4]).group(1),
                    })

        if not col_words:
            continue

        # If period wasn't in the column header word, try to find period in preceding context
        if len(col_words) == 1 and not col_words[0]["period"]:
            ctx_year = _YEAR_PATTERN.search(combined_context)
            if ctx_year:
                col_words[0]["period"] = ctx_year.group(1)

        # Build column intervals
        col_intervals: list[tuple[float, float]] = []
        if len(col_words) == 1:
            label_max_x = col_words[0]["x0"] - 15.0
            col_intervals.append((label_max_x, 10000.0))
        else:
            # Multi-column table
            label_max_x = (header_line["x0"] + col_words[0]["x0"]) / 2.0 if header_line["x0"] < col_words[0]["x0"] - 40 else col_words[0]["x0"] - 15.0
            for i in range(len(col_words)):
                left_bound = (
                    label_max_x
                    if i == 0
                    else (col_words[i - 1]["x_center"] + col_words[i]["x_center"]) / 2.0
                )
                right_bound = (
                    10000.0
                    if i == len(col_words) - 1
                    else (col_words[i]["x_center"] + col_words[i + 1]["x_center"]) / 2.0
                )
                col_intervals.append((left_bound, right_bound))

        # Create TableColumn definitions: Column 0 is the metric label column
        columns: list[TableColumn] = [
            TableColumn(
                index=0,
                header_path=["Financial Metric"],
                role="label",
            )
        ]
        header_row_texts: list[str | None] = ["Financial Metric"]
        for idx, cw in enumerate(col_words):
            p_val = cw["period"]
            col_header = cw["text"]
            header_row_texts.append(col_header)
            columns.append(
                TableColumn(
                    index=idx + 1,
                    header_path=[col_header],
                    period=p_val,
                    currency=currency,
                    multiplier=multiplier,
                    role="value",
                    frequency="duration" if re.search(r"income|cash flow", table_title, re.IGNORECASE) else "instant",
                    period_kind="duration" if re.search(r"income|cash flow", table_title, re.IGNORECASE) else "instant",
                    consolidation="consolidated" if "consolidated" in combined_context.lower() else "unspecified",
                    basis="reported",
                )
            )

        # 4. Extract Data Rows
        rows: list[TableRow] = []
        table_warnings: list[str] = []
        row_idx = 0
        min_table_x = header_line["x0"]
        max_table_x = header_line["x1"]
        min_table_y = header_line["y0"]
        max_table_y = header_line["y1"]

        has_any_ocr_substitution = False
        last_table_line_idx = h_idx
        consecutive_non_numeric = 0

        for line_idx in range(h_idx + 1, len(lines)):
            line = lines[line_idx]
            line_text = line["text"]

            # Check for table termination (commentary, notes, new section, or footer)
            if re.search(
                r"\b(?:management\s+commentary|notes\s+to|disclosed\s+business|fictional\s+development|page\s+\d+)\b",
                line_text,
                re.IGNORECASE,
            ):
                break

            # Separate words into Label (Column 0) and Data Columns (1..N)
            label_words = [w for w in line["words"] if (w[0] + w[2]) / 2.0 < label_max_x]
            row_label = " ".join(w[4] for w in label_words).strip()

            # If no label words, but line has numeric tokens, check if label is merged on previous line
            if not row_label and rows and line_idx > h_idx + 1:
                # Could be continuation or subtotal
                row_label = f"Line Item {row_idx + 1}"

            cell_values: list[FinancialCell] = [
                FinancialCell(
                    raw=row_label,
                    value=None,
                    kind="text",
                )
            ]
            has_valid_cell = False

            for c_idx, (c_min, c_max) in enumerate(col_intervals):
                c_words = [
                    w for w in line["words"] if c_min <= (w[0] + w[2]) / 2.0 < c_max
                ]
                cell_raw = " ".join(w[4] for w in c_words).strip()

                if cell_raw:
                    # Clean OCR substitutions
                    cleaned_raw, sub_applied = _clean_ocr_numeric_substitutions(cell_raw)
                    if sub_applied:
                        has_any_ocr_substitution = True

                    cell = normalize_financial_cell(
                        raw=cleaned_raw,
                        currency=currency,
                        multiplier=multiplier,
                    )
                    if cell.value is not None:
                        has_valid_cell = True
                else:
                    cell = FinancialCell(
                        raw="",
                        value=None,
                        currency=currency,
                        multiplier=multiplier,
                        kind="missing",
                    )
                cell_values.append(cell)

            if row_label and has_valid_cell:
                min_table_x = min(min_table_x, line["x0"])
                max_table_x = max(max_table_x, line["x1"])
                max_table_y = max(max_table_y, line["y1"])

                rows.append(
                    TableRow(
                        index=row_idx,
                        label=row_label,
                        cells=cell_values,
                        kind="data",
                    )
                )
                row_idx += 1
                last_table_line_idx = line_idx
                consecutive_non_numeric = 0
            else:
                consecutive_non_numeric += 1
                if len(rows) >= 2 and consecutive_non_numeric >= 2:
                    break

        if len(rows) < 2:
            continue

        last_consumed_line_idx = max(last_consumed_line_idx, last_table_line_idx)

        if has_any_ocr_substitution:
            table_warnings.append("ocr_character_substitution_detected")

        # 5. Accounting Consistency Validation
        # Check Revenue - Cost of Sales == Gross Profit if all three are present
        status: Literal["certain", "uncertain"] = "certain"
        labels_lower = [r.label.lower() for r in rows]

        rev_idx = next((i for i, l in enumerate(labels_lower) if "revenue" in l or "total sales" in l), None)
        cost_idx = next((i for i, l in enumerate(labels_lower) if "cost of sales" in l or "cost of goods" in l or "cogs" in l), None)
        gp_idx = next((i for i, l in enumerate(labels_lower) if "gross profit" in l or "gross margin" in l), None)

        if rev_idx is not None and cost_idx is not None and gp_idx is not None:
            for col_i in range(1, len(columns)):
                rev_val = rows[rev_idx].cells[col_i].value
                cost_val = rows[cost_idx].cells[col_i].value
                gp_val = rows[gp_idx].cells[col_i].value

                if rev_val is not None and cost_val is not None and gp_val is not None:
                    # Abs cost for calculation since cost may be signed negative or positive
                    abs_cost = abs(cost_val)
                    expected_gp = rev_val - abs_cost
                    if abs(expected_gp - gp_val) > Decimal("0.05"):
                        status = "uncertain"
                        table_warnings.append(
                            f"ocr_accounting_reconciliation_conflict_col_{col_i}"
                        )
                        break

        # Deterministic UUID5 for table
        table_id = uuid5(
            NAMESPACE_URL,
            f"{document_id}:page{page_number}:ocr_table:{table_title}:{len(rows)}",
        )

        bbox = (
            round(min_table_x, 2),
            round(min_table_y, 2),
            round(max_table_x, 2),
            round(max_table_y, 2),
        )

        tables.append(
            FinancialTable(
                table_id=table_id,
                document_id=document_id,
                page_number=page_number,
                bbox=bbox,
                title=table_title,
                entity_context=combined_context,
                row_count=len(rows),
                column_count=len(columns),
                header_rows=[header_row_texts],
                columns=columns,
                rows=rows,
                warnings=table_warnings,
                status=status,
                method="Tesseract.ocr/scanned_table",
            )
        )

    return tables


def narrative_outside_ocr_tables(
    words: list[tuple[float, float, float, float, str, int, int, int]],
    tables: list[FinancialTable],
) -> str:
    """Extract narrative prose words from OCR results located outside recognized table boundaries."""

    if not words:
        return ""

    outside_words = []
    for w in words:
        x_mid = (w[0] + w[2]) / 2.0
        y_mid = (w[1] + w[3]) / 2.0
        inside_any = False
        for table in tables:
            bx0, by0, bx1, by1 = table.bbox
            if bx0 <= x_mid <= bx1 and by0 <= y_mid <= by1:
                inside_any = True
                break
        if not inside_any:
            outside_words.append(w)

    lines = _group_words_into_lines(outside_words, y_tolerance=8.0)
    paragraphs = []
    current_para = []

    for idx, line in enumerate(lines):
        line_text = line["text"]
        if not line_text:
            continue
        if idx > 0 and line["y0"] - lines[idx - 1]["y1"] > 16.0:
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
        current_para.append(line_text)

    if current_para:
        paragraphs.append(" ".join(current_para))

    return "\n\n".join(paragraphs).strip()
