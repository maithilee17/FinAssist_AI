"""Conservative column-aware proofs; never infer absent cells or accounting scope."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext

from app.services.financial_cell_normalizer import normalize_financial_cell
from app.services.financial_table_extractor import TABLE_MARKER, decode_table_chunk
from app.services.question_requirements import QuestionRequirementAnalyzer
from app.services.vector_store import VectorSearchResult

ALIASES = {
    "inventory": ("inventory", "inventories"),
    "revenue": (
        "revenue",
        "total revenue",
        "sales",
        "turnover",
        "revenue from operations",
    ),
    "cost of sales": (
        "cost of sales",
        "cost of goods sold",
        "cost of goods sold (cogs)",
        "cogs",
    ),
    "gross profit": ("gross profit",),
    "net income": ("net income", "net profit"),
    "operating income": ("operating income", "operating profit"),
    "total liabilities": ("total liabilities",),
    "total assets": ("total assets",),
    "net cash change": (
        "net change in cash",
        "net increase in cash",
        "net cash increase",
    ),
    "operating cash flow": (
        "operating cash flow",
        "net cash from operating activities",
        "net cash used in operating activities",
        "net cash provided by operating activities",
    ),
    "investing cash flow": (
        "investing cash flow",
        "net cash from investing activities",
        "net cash used in investing activities",
        "net cash provided by investing activities",
    ),
    "financing cash flow": (
        "financing cash flow",
        "net cash from financing activities",
        "net cash used in financing activities",
        "net cash provided by financing activities",
    ),
}


def table_query(question: str, evidence: list[VectorSearchResult]) -> bool:
    """Only numeric financial requests take the deterministic table route."""
    from app.services.financial_calculation import calculation_kind

    structured_documents = {
        x.document_id for x in evidence if x.chunk_text.startswith(TABLE_MARKER)
    }
    # Preserve the existing grounded RAG route for factual comparisons involving
    # old text-only indexes. A table-only proof cannot silently omit that issuer.
    # Arithmetic continues to fail closed until all required inputs are structured.
    if (
        structured_documents
        and structured_documents != {x.document_id for x in evidence}
        and re.search(r"\bcompare|comparison|versus|\bvs\b", question, re.IGNORECASE)
        and not calculation_kind(question)
        and not re.search(r"calculat|comput|growth|reconcil", question, re.IGNORECASE)
    ):
        return False
    return (
        any(x.chunk_text.startswith("[FINASSIST_TABLE_") for x in evidence)
        and bool(
            re.search(
                r"inventory|revenue|sales|income|profit|margin|liabilit|assets|cash flow|cash change|change in cash|\btables?\b",
                question,
                re.IGNORECASE,
            )
        )
        and not bool(
            re.search(
                r"risk|why|strategy|products?|manufactur|sales model",
                question,
                re.IGNORECASE,
            )
        )
    )


def calculate_table(question: str, evidence: list[VectorSearchResult]):
    with localcontext() as context:
        context.prec = 64
        try:
            return _calculate_table(question, evidence)
        except DecimalException:
            return None


def _calculate_table(question: str, evidence: list[VectorSearchResult]):
    from app.services.financial_calculation import Calculation, FinancialInput

    if not table_query(question, evidence) or len({x.user_id for x in evidence}) != 1:
        return None
    requirements = QuestionRequirementAnalyzer().analyze(question)
    if requirements.conceptual_topics or requirements.is_ambiguous:
        return None
    years = sorted(set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", question)))
    q = question.lower()
    operation = next(
        (
            name
            for name, pattern in (
                ("gross profit margin", r"gross(?: profit)?\s+margin"),
                ("net profit margin", r"net(?: profit)?\s+margin"),
                ("operating margin", r"operating(?: profit)?\s+margin"),
                ("debt-to-assets", r"debt.*assets"),
                ("revenue growth", r"revenue.*growth|growth.*revenue"),
                (
                    "net cash change",
                    r"net\s+(?:cash\s+change|change\s+in\s+cash|increase\s+in\s+cash)|cash.*reconcil|reconcil.*cash",
                ),
            )
            if re.search(pattern, q)
        ),
        None,
    )
    if (
        len(
            re.findall(
                r"(?:gross(?: profit)?|net(?: profit)?|operating(?: profit)?)\s+margin|revenue growth|debt.to.assets",
                q,
            )
        )
        > 1
    ):
        return None
    explicit_metrics = [
        metric
        for metric, aliases in ALIASES.items()
        if any(re.search(rf"\b{re.escape(a)}\b", q) for a in aliases)
    ]
    metrics = list(explicit_metrics)
    if operation:
        metrics = {
            "gross profit margin": ["revenue", "gross profit", "cost of sales"],
            "net profit margin": ["net income", "revenue"],
            "operating margin": ["operating income", "revenue"],
            "debt-to-assets": ["total liabilities", "total assets"],
            "revenue growth": ["revenue"],
            "net cash change": [
                "net cash change",
                "operating cash flow",
                "investing cash flow",
                "financing cash flow",
            ],
        }[operation]
    elif not explicit_metrics and re.search(
        r"income statement|financial table|three.year.*table|multi.year.*table", q
    ):
        metrics = [
            "revenue",
            "cost of sales",
            "gross profit",
            "net income",
            "operating income",
        ]
    elif not explicit_metrics and re.search(r"balance sheet", q):
        metrics = ["total assets", "total liabilities"]
    elif not explicit_metrics and re.search(r"cash flows?", q):
        metrics = ["operating cash flow", "investing cash flow", "financing cash flow"]
    if not metrics:
        return None
    covered = {a for metric in metrics for a in ALIASES[metric]}
    if any("profit" in a or "income" in a for a in covered):
        covered.update({"profit", "income"})
    if "total assets" in covered:
        covered.add("assets")
    if "total liabilities" in covered:
        covered.add("liabilities")
    if operation and "margin" in operation:
        covered.add("margin")
    if operation == "debt-to-assets":
        covered.add("debt")
    if any("cash flow" in a for a in covered):
        covered.add("cash flow")
    if any(metric not in covered for metric in requirements.metrics):
        return None
    # Each key includes issuer document, reporting period, currency and scope.
    groups = {}
    names = {}
    for source_number, item in enumerate(evidence, 1):
        if not item.chunk_text.startswith(TABLE_MARKER):
            continue
        table = decode_table_chunk(item.chunk_text)
        if (
            not table
            or table.status != "certain"
            or table.document_id != item.document_id
            or table.page_number not in item.page_numbers
            or not item.filename
            or not item.chunk_id
        ):
            return None
        if requirements.company_names and not any(
            name.lower() in table.entity_context.lower()
            for name in requirements.company_names
        ):
            continue
        names[item.document_id] = table.entity_context.splitlines()[0]
        for column in table.columns[1:]:
            if (
                column.role != "value"
                or not column.period
                or (years and column.period not in years)
            ):
                continue
            # Actual/forecast and consolidated/standalone cannot be blended.
            key = (
                item.document_id,
                column.period,
                column.frequency,
                column.consolidation,
                column.basis,
                column.currency,
                column.reporting_date,
                column.period_kind,
            )
            for row in table.rows:
                label = " ".join(row.label.lower().split())
                metric = next(
                    (m for m, aliases in ALIASES.items() if label in aliases), None
                )
                if metric not in metrics:
                    continue
                facts = groups.setdefault(key, {})
                cell = row.cells[column.index]
                independently_parsed = normalize_financial_cell(
                    cell.raw, currency=column.currency, multiplier=column.multiplier
                )
                valid = (
                    independently_parsed.value == cell.value
                    and independently_parsed.currency == cell.currency
                    and cell.kind == "number"
                    and cell.value is not None
                    and cell.currency
                    and not cell.warnings
                    and not row.section_path
                    and not table.notes
                )
                excerpt = f"{table.title}; {names[item.document_id]}; {column.period}; {' / '.join(column.header_path)}; {column.frequency}, {column.consolidation}, {column.basis}; {row.label}: {cell.raw}; {cell.currency}, multiplier {cell.multiplier}; table {table.table_id}, row {row.index}, column {column.index}"
                fact = FinancialInput(
                    metric,
                    cell.value or Decimal(0),
                    cell.currency or "",
                    source_number,
                    item.chunk_id,
                    item.document_id,
                    item.user_id,
                    item.filename,
                    tuple(item.page_numbers),
                    0,
                    len(item.chunk_text),
                    excerpt,
                )
                prior = facts.get(metric)
                if not valid or (prior and prior.amount != fact.amount):
                    facts[metric] = False
                elif prior is not False:
                    facts[metric] = fact
    if not groups:
        return None
    # Multiple scopes for one issuer/year require an explicit selector.
    selected = {}
    for key, facts in groups.items():
        if key[4] in {"budget", "forecast"} and key[4] not in q:
            continue
        if key[3] in {"consolidated", "standalone"} and any(
            s in q and s != key[3] for s in ("consolidated", "standalone")
        ):
            continue
        quarter = re.search(r"\bq[1-4]\b", q)
        if quarter and key[2].lower() != f"quarterly:{quarter.group().upper()}".lower():
            continue
        if key[:2] in selected:
            return None
        selected[key[:2]] = (key, facts)
    documents = {key[0] for key in selected}
    if not documents:
        return None
    if (
        requirements.requires_comparison
        and re.search(r"\b(?:two|both) companies\b", q)
        and len(documents) != 2
    ):
        return None
    if (
        not years
        and len({k[1] for k in selected}) > 1
        and not requirements.requires_comparison
        and not re.search(r"summar|multi.year|three.year", q)
    ):
        return None
    if requirements.company_names and any(
        not any(name.lower() in names[d].lower() for d in documents)
        for name in requirements.company_names
    ):
        return None
    if len(documents) > 1 and not requirements.requires_comparison:
        return None
    table_format = bool(re.search(r"\btables?\b", q))
    display_labels = {
        "revenue": "Revenue",
        "cost of sales": "Cost of Sales",
        "gross profit": "Gross Profit",
        "net income": "Net Income",
        "operating income": "Operating Income",
        "total assets": "Total Assets",
        "total liabilities": "Total Liabilities",
        "operating cash flow": "Operating Cash Flow",
        "investing cash flow": "Investing Cash Flow",
        "financing cash flow": "Financing Cash Flow",
        "net cash change": "Net Cash Change",
    }
    lines = [
        "Verified table financial analysis (normalized amounts in base currency units):"
    ]
    inputs = []
    for doc in sorted(documents, key=str):
        periods = years or sorted(k[1] for k in selected if k[0] == doc)
        if any((doc, year) not in selected for year in periods):
            return None
        if operation == "revenue growth" and len(periods) != 2:
            return None
        if (
            operation == "revenue growth"
            and re.search(r"year.over.year|year.on.year|\byoy\b", q)
            and int(periods[1]) - int(periods[0]) != 1
        ):
            return None
        doc_operands = {}
        for year in periods:
            key, facts = selected[(doc, year)]
            used = [
                m
                for m in metrics
                if not (operation == "net cash change" and m == "net cash change")
            ]
            if not explicit_metrics and not operation:
                used = [
                    m
                    for m in used
                    if all(
                        facts_y.get(m)
                        for (d_k, _), (_, facts_y) in selected.items()
                        if d_k == doc
                    )
                ]
                if not used:
                    return None
            if operation == "gross profit margin":
                if facts.get("revenue") and facts.get("cost of sales"):
                    used = ["revenue", "cost of sales"]
                    if facts.get("gross profit") is False or (
                        facts.get("gross profit")
                        and facts["gross profit"].amount
                        != facts["revenue"].amount - facts["cost of sales"].amount
                    ):
                        return None
                else:
                    if facts.get("cost of sales") is False:
                        return None
                    used = ["gross profit", "revenue"]
            if any(not facts.get(m) for m in used):
                return None
            operands = [facts[m] for m in used]
            if len({f.currency for f in operands}) != 1:
                return None
            inputs.extend(operands)
            doc_operands[year] = (key, facts, operands, used)

        if table_format and not operation:
            first_key = doc_operands[periods[0]][0]
            scope = f"{names[doc]} ({first_key[2]}, {first_key[3]}, {first_key[4]})" + (
                f", as of {first_key[6]}" if first_key[6] else ""
            )
            lines.append(f"{scope}:")
            headers = (
                ["Financial Metric"] + [f"FY{year}" for year in periods] + ["Citations"]
            )
            lines.append("| " + " | ".join(headers) + " |")
            lines.append(
                "| "
                + " | ".join([":---"] + ["---:" for _ in periods] + [":---"])
                + " |"
            )
            first_operands = doc_operands[periods[0]][2]
            for idx, fact_template in enumerate(first_operands):
                label = display_labels.get(
                    fact_template.label, fact_template.label.title()
                )
                row_vals = []
                row_sources = set()
                for year in periods:
                    f = doc_operands[year][2][idx]
                    row_vals.append(f"{f.amount:,.2f} {f.currency}")
                    row_sources.add(f.source_number)
                citations_str = " ".join(f"[Source {n}]" for n in sorted(row_sources))
                lines.append(
                    f"| {label} | " + " | ".join(row_vals) + f" | {citations_str} |"
                )
        else:
            for year in periods:
                key, facts, operands, used = doc_operands[year]
                citations = " ".join(
                    f"[Source {n}]" for n in sorted({f.source_number for f in operands})
                )
                scope = f"{names[doc]}, FY{year}, {key[2]}, {key[3]}, {key[4]}" + (
                    f", as of {key[6]}" if key[6] else ""
                )
                displayed = "; ".join(
                    f"{f.label} = {f.amount:,.2f} {f.currency}" for f in operands
                )
                lines.append(f"{scope}: {displayed} {citations}.")
                if not operation or operation == "revenue growth":
                    continue
                a = operands[0].amount
                b = operands[1].amount
                if operation == "net cash change":
                    value = sum((f.amount for f in operands), Decimal(0))
                    reported = facts.get("net cash change")
                    if reported is False or (
                        reported
                        and (
                            reported.amount != value
                            or reported.currency != operands[0].currency
                        )
                    ):
                        return None
                    expression = " + ".join(f"({f.amount:f})" for f in operands)
                    suffix = operands[0].currency
                else:
                    if operation == "gross profit margin" and used == [
                        "revenue",
                        "cost of sales",
                    ]:
                        a, b = a - b, a
                    if b <= 0:
                        return None
                    value = a / b * 100
                    expression, suffix = f"{a:f} / {b:f} * 100", "%"
                lines.append(
                    f"{operation}: {expression} = {value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}{suffix} {citations}."
                )
        if operation == "revenue growth":
            old_key, old = selected[(doc, periods[0])]
            new_key, new = selected[(doc, periods[1])]
            if old_key[2:] != new_key[2:] or old["revenue"].amount <= 0:
                return None
            a, b = new["revenue"], old["revenue"]
            value = ((a.amount - b.amount) / b.amount * 100).quantize(
                Decimal(".01"), rounding=ROUND_HALF_UP
            )
            growth_citations = " ".join(
                f"[Source {n}]" for n in sorted({a.source_number, b.source_number})
            )
            lines.append(
                f"Revenue growth FY{periods[0]} to FY{periods[1]}: ({a.amount:f} - {b.amount:f}) / {b.amount:f} * 100 = {value}% {growth_citations}."
            )
    return Calculation(
        "\n".join(lines),
        tuple(sorted({f.source_number for f in inputs})),
        tuple(inputs),
    )
