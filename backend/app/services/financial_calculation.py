"""Conservative Decimal calculations from unambiguous, labelled source figures.

Never combine companies/documents or infer missing units/period columns. Ambiguous
tables remain on the abstention path rather than guessing which figure to use.
"""

import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.services.vector_store import VectorSearchResult

_ALIASES = {
    "revenue": r"(?:total revenue|revenue|sales)",
    "COGS": r"(?:cost of goods sold(?:\s*\(COGS\))?|COGS)",
    "gross profit": r"gross profit",
    "net profit": r"(?:net profit|net income)",
    "operating profit": r"(?:operating profit|operating income)",
    "total liabilities": r"total liabilities",
    "total assets": r"total assets",
    "current assets": r"current assets",
    "current liabilities": r"current liabilities",
    "ending cash": r"(?:cash at end of year|ending cash)",
    "beginning cash": r"(?:cash at beginning of year|beginning cash)",
    "net cash increase": r"(?:net increase in cash|net change in cash)",
    "operating cash flow": r"(?:(?:net )?cash (?:from|provided by|used in) operating activities|operating cash flows?)",
    "investing cash flow": r"(?:(?:net )?cash (?:from|provided by|used in) investing activities|investing cash flows?)",
    "financing cash flow": r"(?:(?:net )?cash (?:from|provided by|used in) financing activities|financing cash flows?)",
}
_CASH_LABELS = {"operating cash flow", "investing cash flow", "financing cash flow"}
_CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
_CURRENCY = r"(?:USD|EUR|GBP|INR|[$€£₹])"
# Accept standard comma grouping, never silently repair malformed digits.
_NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_AMOUNT = re.compile(
    rf"(?P<unit>{_CURRENCY})\s*(?P<number>{_NUMBER})"
    r"\s*(?P<scale>thousand|million|billion)?[.;]?",
    re.IGNORECASE,
)
_CASH_AMOUNT = re.compile(
    rf"(?P<open>\()?\s*(?P<leading>-)?(?P<unit>{_CURRENCY})\s*"
    rf"(?P<sign>-)?(?P<number>{_NUMBER})\s*"
    r"(?P<scale>thousand|million|billion)?\s*(?(open)\))[.;]?",
    re.IGNORECASE,
)
# Detects a monetary amount somewhere in a string (not fullmatch).
_HAS_MONETARY = re.compile(rf"{_CURRENCY}\s*{_NUMBER}", re.IGNORECASE)
_VALUE_ONLY = re.compile(
    rf"(?:{_CURRENCY}\s*)?[-(]?{_NUMBER}\)?%?(?:\s+(?:thousand|million|billion))?[.;]?"
    rf"|{_CURRENCY}|thousand|million|billion",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_PERIOD_CONTEXT = re.compile(
    r"(?:\bFY\s*[-']?\s*|\b(?:fiscal|financial|reporting)\s+year\s*[:\-]?\s*"
    r"|\byear\s+ended[^\n]{0,60}?)(?P<year>(?:19|20)\d{2})(?!\d)",
    re.IGNORECASE,
)


def calculation_period_error(question, evidence):
    """Only a single, explicitly supported reporting year is calculable.

    Multi-period tables still require a column-aware parser. A question's year
    is a constraint to validate, not a reason to reject otherwise valid inputs.
    """
    requested = set(_YEAR.findall(question))
    supported = set(_YEAR.findall("\n".join(x.chunk_text for x in evidence)))
    explicit = {
        match.group("year")
        for item in evidence
        for match in _PERIOD_CONTEXT.finditer(item.chunk_text)
    }
    if len(requested) > 1 or len(supported) > 1:
        return "unambiguous single reporting period (multiple years found)"
    if requested and (requested != supported or requested != explicit):
        return "requested reporting period explicitly supported by the evidence"
    return None


def _normalize_row(text: str) -> str:
    """Normalize a parsing copy only; citation spans retain the original text."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    # A comma followed by a PDF line break within a three-digit group.
    text = re.sub(r",[ \t]*\n[ \t]*(?=[0-9]{3}\b)", ",", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*\|\s*", " ", text).strip()


@dataclass(frozen=True)
class FinancialInput:
    label: str
    amount: Decimal
    currency: str
    source_number: int
    chunk_id: UUID
    document_id: UUID
    user_id: UUID
    filename: str
    page_numbers: tuple[int, ...]
    start: int
    end: int
    excerpt: str


_ALLOWED_TAIL_WORDS = {
    "usd",
    "eur",
    "gbp",
    "inr",
    "yen",
    "thousand",
    "million",
    "billion",
    "was",
    "were",
    "is",
    "are",
}


def _deduplicate_inputs(
    values: list[FinancialInput],
) -> list[FinancialInput]:
    """Collapse repeated identical mentions into one per (amount, currency, document, user) tuple.

    Identical values from the same document and user (e.g. executive summary,
    income statement, and ratio note all quoting Revenue: $850,000) are accepted
    as one unambiguous input, retaining the first occurrence's full citation.
    Different amounts or currencies produce distinct tuples and are detected as
    conflicts by the caller.
    """
    seen: dict[tuple, FinancialInput] = {}
    result: list[FinancialInput] = []
    for value in values:
        key = (value.amount, value.currency, value.document_id, value.user_id)
        if key not in seen:
            seen[key] = value
            result.append(value)
    return result


def extract_calculation_inputs(
    evidence: list[VectorSearchResult],
) -> tuple[dict[str, FinancialInput], set[str]]:
    """Read bounded, single-value rows, including vertically extracted cells.

    Never join across chunks, skip intervening labels, infer units from a table
    heading, or pick a column in a multi-value row. A genuinely malformed or
    ambiguous data row (label + unparseable monetary value) invalidates that
    metric even when a second occurrence is parseable. Non-data references
    (label in descriptive text without any monetary value, or section headings)
    do not invalidate.
    """
    found: dict[str, list[FinancialInput]] = {label: [] for label in _ALIASES}
    invalid: set[str] = set()
    for source_number, item in enumerate(evidence, 1):
        lines = list(re.finditer(r"[^\n]+", item.chunk_text))
        for position, line in enumerate(lines):
            curr_text = line.group().strip()
            curr_has_money = bool(_HAS_MONETARY.search(curr_text))
            prev_is_bare_label = False
            if position > 0 and not curr_has_money:
                prev_text = lines[position - 1].group().strip()
                prev_is_bare_label = any(
                    re.match(rf"^{a}(?!\w)", prev_text, re.IGNORECASE)
                    for a in _ALIASES.values()
                ) and not bool(_HAS_MONETARY.search(prev_text))

            for label, alias in _ALIASES.items():
                # At most six physical lines / 400 characters per row. Matching
                # the entire row prevents a value from a different metric being
                # consumed after a label-only cell.
                candidates = []
                recognized = False
                has_data_row_failure = False
                max_lookahead = 1 if prev_is_bare_label else 6
                for stop in range(position, min(position + max_lookahead, len(lines))):
                    end = lines[stop].end()
                    if end - line.start() > 400:
                        break

                    # When extending past the initial line (stop > position),
                    # never cross into a line that starts with another metric's label.
                    if stop > position:
                        curr_line_text = lines[stop].group().strip()
                        if any(
                            re.match(
                                rf"^{other_alias}(?!\w)", curr_line_text, re.IGNORECASE
                            )
                            for other_alias in _ALIASES.values()
                        ):
                            break

                    raw = item.chunk_text[line.start() : end]
                    row = _normalize_row(raw)
                    prefix = re.match(
                        rf"^{alias}(?!\w)(?!\s+margin\b)", row, re.IGNORECASE
                    )
                    if not prefix:
                        continue
                    recognized = True
                    tail = row[prefix.end() :].strip()

                    # Determine if the tail contains descriptive non-amount words.
                    tail_for_data_check = re.sub(
                        r"^(?::|=|was\b|were\b|is\b|are\b|\|)\s*",
                        "",
                        tail,
                        flags=re.IGNORECASE,
                    ).strip()
                    row_has_money = bool(_HAS_MONETARY.search(tail_for_data_check))

                    # Check for non-amount descriptive words on this line.
                    tail_words = [
                        w.lower()
                        for w in re.findall(r"\b[A-Za-z]+\b", tail_for_data_check)
                    ]
                    has_descriptive_words = any(
                        w not in _ALLOWED_TAIL_WORDS for w in tail_words
                    )

                    if re.search(r"\|\s*\|", raw):
                        # Empty columns carry layout meaning; do not collapse
                        # them into a falsely unambiguous two-cell table.
                        if row_has_money:
                            has_data_row_failure = True
                        continue

                    match = (
                        _CASH_AMOUNT if label in _CASH_LABELS else _AMOUNT
                    ).fullmatch(tail_for_data_check)
                    if not match and label not in _CASH_LABELS:
                        # Check multi-line formula row in a table (e.g. Current assets \n Cash + Receivables + Inventory \n $300,000)
                        if stop > position and "=" not in tail_for_data_check:
                            amt_matches = list(_AMOUNT.finditer(tail_for_data_check))
                            if (
                                len(amt_matches) == 1
                                and tail_for_data_check[amt_matches[0].end() :]
                                .strip()
                                .rstrip(".;")
                                == ""
                            ):
                                formula_prefix = tail_for_data_check[
                                    : amt_matches[0].start()
                                ].strip()
                                if any(
                                    op in formula_prefix
                                    for op in ("+", "-", "*", "/", "x", "×")
                                ):
                                    match = amt_matches[0]
                        # Check totaling sentence (e.g. Current liabilities are accounts payable of $90,000..., totaling $160,000.)
                        if not match and "total" in tail_for_data_check.lower():
                            totaling_match = re.search(
                                r"\btotal(?:ing|ling)\s+(?:to\s+)?(?P<rest>[^.]+)",
                                tail_for_data_check,
                                re.IGNORECASE,
                            )
                            if totaling_match:
                                tot_amt = _AMOUNT.search(totaling_match.group("rest"))
                                if tot_amt:
                                    match = tot_amt

                    if not match:
                        if (
                            stop == position
                            and tail_words
                            and tail_words[0] not in _ALLOWED_TAIL_WORDS
                        ):
                            # A formula, heading, or narrative sentence that begins with
                            # descriptive text (e.g. "Gross profit minus operating expenses = $160,000",
                            # "Revenue Analysis", "Gross profit divided by Revenue").
                            # This is not a data row for this metric and must not invalidate it.
                            break
                        if row_has_money:
                            # Only a failed data row (monetary value present but
                            # unparseable as a single unambiguous amount) counts
                            # as a genuine ambiguity that should invalidate.
                            has_data_row_failure = True
                        elif stop == position and has_descriptive_words:
                            break
                        continue

                    # Vertically extracted multiple columns must not be treated
                    # as a single-value row by stopping at the first amount.
                    next_line = lines[stop + 1] if stop + 1 < len(lines) else None
                    if next_line and (
                        _VALUE_ONLY.fullmatch(_normalize_row(next_line.group()))
                        or _CASH_AMOUNT.fullmatch(_normalize_row(next_line.group()))
                    ):
                        if row_has_money:
                            has_data_row_failure = True
                        continue

                    unit, number, scale = match.group("unit", "number", "scale")
                    amount = Decimal(number.replace(",", "")) * {
                        "thousand": 1000,
                        "million": 1000000,
                        "billion": 1000000000,
                    }.get((scale or "").lower(), 1)
                    if label in _CASH_LABELS:
                        signs = sum(
                            bool(match.group(key))
                            for key in ("open", "leading", "sign")
                        )
                        if signs > 1:
                            has_data_row_failure = True
                            continue
                        if signs:
                            amount = -amount
                    candidates.append(
                        FinancialInput(
                            label,
                            amount,
                            _CURRENCIES.get(unit, unit.upper()),
                            source_number,
                            item.chunk_id,
                            item.document_id,
                            item.user_id,
                            item.filename,
                            tuple(item.page_numbers),
                            line.start(),
                            end,
                            raw,
                        )
                    )
                    break
                if candidates:
                    found[label].extend(candidates)
                elif recognized and has_data_row_failure:
                    # Only invalidate when the label appeared in a row that
                    # contained a monetary value but couldn't be unambiguously
                    # parsed (multi-column, empty-column, or extra trailing
                    # values). Pure descriptive mentions are not data rows.
                    invalid.add(label)
    facts = {}
    for label, values in found.items():
        deduped = _deduplicate_inputs(values)
        if len({(v.amount, v.currency) for v in deduped}) > 1:
            invalid.add(label)
        if deduped and label not in invalid:
            facts[label] = deduped[0]
    return facts, invalid


def _format_currency(amount: Decimal, currency: str) -> str:
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, "")
    if amount == amount.to_integral_value():
        formatted_num = f"{int(amount):,}"
    else:
        formatted_num = f"{amount:,.2f}"
    return f"{sym}{formatted_num}" if sym else f"{formatted_num} {currency}"


def calculation_kind(question):
    text = question.lower()
    if re.search(
        r"reconcil.*cash|cash.*reconcil|ending cash\s*=\s*beginning cash",
        text,
    ):
        return "ending cash reconciliation"
    if re.search(
        r"gross.*margin|gross profit divided by revenue|percentage of revenue.*cogs",
        text,
    ):
        return "gross margin"
    for pattern, kind in [
        (r"net (?:profit |income )?margin", "net margin"),
        (r"operating (?:profit )?margin", "operating margin"),
        (r"debt[ -]to[ -]assets", "debt-to-assets"),
        (r"current ratio", "current ratio"),
        (r"working capital", "working capital"),
        (r"gross profit", "gross profit"),
        (
            r"net (?:change|increase|decrease) in cash|cash flow net change",
            "net change in cash",
        ),
    ]:
        if re.search(pattern, text):
            return kind
    return None


@dataclass(frozen=True)
class Calculation:
    answer: str
    sources: tuple[int, ...]
    inputs: tuple[FinancialInput, ...] = ()
    reporting_period: str | None = None
    discrepancy: bool = False


def is_composite_financial_query(question):
    """Intent differs from merely mentioning a calculable metric in prose."""
    summary = bool(
        re.search(
            r"\b(?:summari[sz]e|summary|overview|describe|discuss|explain)\b",
            question,
            re.IGNORECASE,
        )
    )
    topics = sum(
        bool(re.search(alias, question, re.IGNORECASE)) for alias in _ALIASES.values()
    )
    cash = bool(re.search(r"\bcash flows?\b", question, re.IGNORECASE))
    return summary and (cash or topics > 1)


def is_cash_flow_summary(question):
    return is_composite_financial_query(question) and bool(
        re.search(r"\bcash flows?\b", question, re.IGNORECASE)
    )


def cash_flow_summary(question, evidence):
    """Complete, source-backed cash-flow explanation and independently checked net.

    No narrative causation is invented: inflow/outflow follows the sign. Period,
    entity and original money-unit text are preserved. Different documents are
    never combined, even when all selected documents belong to the same user.
    """
    if not is_cash_flow_summary(question) or not evidence:
        return None
    if re.search(
        r"\b(?:why|risks?|drivers?|causes?|outlook|reasons?|revenue|profits?|assets|liabilities)\b",
        question,
        re.IGNORECASE,
    ):
        # Do not silently omit additional requests from a cash-only answer.
        return None
    if len({x.user_id for x in evidence}) != 1 or any(
        not x.chunk_id
        or not x.filename
        or not x.page_numbers
        or any(p < 1 for p in x.page_numbers)
        for x in evidence
    ):
        return None
    from app.services.query_analyzer import extract_company_names

    companies = extract_company_names(question)
    if len(companies) > 1:
        return None
    groups = {}
    for index, row in enumerate(evidence, 1):
        groups.setdefault(row.document_id, []).append((index, row))
    candidates = []
    for group in groups.values():
        rows = [row for _, row in group]
        corpus = "\n".join(row.chunk_text for row in rows)
        if companies and not re.search(
            rf"^\s*{re.escape(companies[0])}\b", corpus, re.IGNORECASE | re.MULTILINE
        ):
            continue
        if calculation_period_error(question, rows):
            continue
        candidates.append(group)
    # A name/period must select exactly one document. Never choose by finding
    # convenient values in different documents, or arbitrarily prefer a version.
    if len(candidates) != 1 or (not companies and len(groups) != 1):
        return None
    group = candidates[0]
    rows = [row for _, row in group]
    facts, invalid = extract_calculation_inputs(rows)
    required = _CASH_LABELS | {"beginning cash", "ending cash", "net cash increase"}
    if invalid & required or not _CASH_LABELS <= facts.keys():
        return None
    facts = {
        key: replace(value, source_number=group[value.source_number - 1][0])
        for key, value in facts.items()
    }
    flows = [
        facts[label]
        for label in (
            "operating cash flow",
            "investing cash flow",
            "financing cash flow",
        )
    ]
    inputs = list(flows)
    net = sum((fact.amount for fact in flows), Decimal(0))
    if "beginning cash" in facts and "ending cash" in facts:
        inputs.extend([facts["beginning cash"], facts["ending cash"]])
        if facts["ending cash"].amount - facts["beginning cash"].amount != net:
            return None
    elif "net cash increase" not in facts:
        # The three activities alone need not include FX/reclassification effects.
        return None
    if "net cash increase" in facts:
        inputs.append(facts["net cash increase"])
        if facts["net cash increase"].amount != net:
            return None
    if len({fact.currency for fact in inputs}) != 1:
        return None
    years = _YEAR.findall(question) or [
        match.group("year")
        for row in rows
        for match in _PERIOD_CONTEXT.finditer(row.chunk_text)
    ]
    period = years[0] if years else None
    sources = {fact.source_number for fact in inputs}
    if period:
        sources.add(
            next(
                index
                for index, row in group
                if any(
                    match.group("year") == period
                    for match in _PERIOD_CONTEXT.finditer(row.chunk_text)
                )
            )
        )
    citations = " ".join(f"[Source {index}]" for index in sorted(sources))
    subject = f" for {companies[0]}" if companies else ""
    heading = f"Verified cash flow summary{subject}{f' for FY{period}' if period else ''} {citations}:"
    lines = [heading]
    for label, fact in zip(("Operating", "Investing", "Financing"), flows, strict=True):
        match = _CASH_AMOUNT.search(_normalize_row(fact.excerpt))
        display = match.group(0).rstrip(".;").strip()
        direction = (
            "net inflow"
            if fact.amount > 0
            else "net outflow"
            if fact.amount < 0
            else "no net cash flow"
        )
        lines.append(
            f"{label} activities: {display} ({direction}) [Source {fact.source_number}]."
        )
    # Use the first activity's explicit scale for the derived total; never label
    # a figure in thousands/millions as a base-unit figure or change currencies.
    unit_match = _CASH_AMOUNT.search(_normalize_row(flows[0].excerpt))
    scale = unit_match.group("scale")
    divisor = {"thousand": 1000, "million": 1000000, "billion": 1000000000}.get(
        (scale or "").lower(), 1
    )
    unit = unit_match.group("unit")
    separator = "" if unit in _CURRENCIES else " "
    display_net = f"{unit}{separator}{net / divisor:,.2f}{f' {scale}' if scale else ''}"
    lines.append(
        f"Net change in cash: {display_net}; operating + investing + financing, independently reconciled to reported cash figures {citations}."
    )
    return Calculation("\n".join(lines), tuple(sorted(sources)), tuple(inputs), period)


def calculate(question, evidence):
    from app.services.structured_financial_calculation import (
        calculate_table,
        table_query,
    )

    if table_query(question, evidence):
        return calculate_table(question, evidence)
    if is_composite_financial_query(question):
        return None
    kind = calculation_kind(question)
    if not kind or not evidence:
        return None
    # Cross-document and multi-period arithmetic still fails closed.
    if (
        len({x.document_id for x in evidence}) != 1
        or len({x.user_id for x in evidence}) != 1
        or any(
            not x.chunk_id
            or not x.filename
            or not x.page_numbers
            or any(page < 1 for page in x.page_numbers)
            for x in evidence
        )
    ):
        return None
    if calculation_period_error(question, evidence):
        return None
    requested_years = _YEAR.findall(question)
    period = requested_years[0] if requested_years else None
    facts, invalid = extract_calculation_inputs(evidence)
    if kind == "ending cash reconciliation":
        if invalid & {"ending cash", "beginning cash", "net cash increase"}:
            return None
        if (
            "ending cash" not in facts
            or "beginning cash" not in facts
            or "net cash increase" not in facts
        ):
            return None
        beg_c = facts["beginning cash"]
        net_inc = facts["net cash increase"]
        end_c = facts["ending cash"]
        if beg_c.currency != net_inc.currency or beg_c.currency != end_c.currency:
            return None
        inputs = (beg_c, net_inc, end_c)
        source_numbers = {fact.source_number for fact in inputs}
        if period:
            for index, item in enumerate(evidence, 1):
                if any(
                    match.group("year") == period
                    for match in _PERIOD_CONTEXT.finditer(item.chunk_text)
                ):
                    source_numbers.add(index)
                    break
        sources = tuple(sorted(source_numbers))
        citations = " ".join(f"[Source {i}]" for i in sources)
        expected_ending = beg_c.amount + net_inc.amount
        is_discrepancy = expected_ending != end_c.amount

        beg_str = _format_currency(beg_c.amount, beg_c.currency)
        net_str = _format_currency(net_inc.amount, net_inc.currency)
        end_str = _format_currency(end_c.amount, end_c.currency)

        if is_discrepancy:
            calc_str = _format_currency(expected_ending, beg_c.currency)
            answer = (
                f"Discrepancy in ending cash reconciliation{f' for FY{period}' if period else ''}:\n"
                f"Beginning cash = {beg_str} [Source {beg_c.source_number}]\n"
                f"Net cash increase = {net_str} [Source {net_inc.source_number}]\n"
                f"Ending cash = {end_str} [Source {end_c.source_number}]\n"
                f"Ending Cash = Beginning Cash + Net Increase in Cash\n"
                f"Calculated: {calc_str} != Reported: {end_str} {citations}."
            )
            return Calculation(answer, sources, inputs, period, discrepancy=True)

        answer = (
            f"Derived ending cash reconciliation{f' for FY{period}' if period else ''}:\n"
            f"Beginning cash = {beg_str} [Source {beg_c.source_number}]\n"
            f"Net cash increase = {net_str} [Source {net_inc.source_number}]\n"
            f"Ending cash = {end_str} [Source {end_c.source_number}]\n"
            f"Ending Cash = Beginning Cash + Net Increase in Cash\n"
            f"{end_str} = {beg_str} + {net_str} {citations}."
        )
        return Calculation(answer, sources, inputs, period, discrepancy=False)

    ratio = kind not in {"gross profit", "working capital", "net change in cash"}
    numerator, denominator = {
        "gross margin": ("gross profit", "revenue"),
        "net margin": ("net profit", "revenue"),
        "operating margin": ("operating profit", "revenue"),
        "debt-to-assets": ("total liabilities", "total assets"),
        "current ratio": ("current assets", "current liabilities"),
        "gross profit": ("revenue", "COGS"),
        "working capital": ("current assets", "current liabilities"),
        "net change in cash": ("ending cash", "beginning cash"),
    }[kind]
    used = [numerator, denominator]
    expression = numerator
    numeric_numerator = None
    if kind in {"gross margin", "gross profit"}:
        # Do not fall back to reported gross profit when COGS/revenue conflict.
        if invalid & {"revenue", "COGS", "gross profit"}:
            return None
        if "revenue" in facts and "COGS" in facts:
            revenue, cogs = facts["revenue"], facts["COGS"]
            if revenue.currency != cogs.currency:
                return None
            gross = revenue.amount - cogs.amount
            if "gross profit" in facts and (
                facts["gross profit"].amount != gross
                or facts["gross profit"].currency != revenue.currency
            ):
                return None
            if kind == "gross margin":
                # Keep both original inputs; never assign derived profit the
                # provenance of revenue alone.
                used = ["revenue", "COGS"]
                expression = "(revenue - COGS)"
                numeric_numerator = f"({revenue.amount:f} - {cogs.amount:f})"
        elif kind == "gross profit" or "gross profit" not in facts:
            return None
    elif kind == "net change in cash":
        if invalid & {"ending cash", "beginning cash", "net cash increase"}:
            return None
        if "ending cash" in facts and "beginning cash" in facts:
            end_c, beg_c = facts["ending cash"], facts["beginning cash"]
            if end_c.currency != beg_c.currency:
                return None
            net_change = end_c.amount - beg_c.amount
            if "net cash increase" in facts and (
                facts["net cash increase"].amount != net_change
                or facts["net cash increase"].currency != end_c.currency
            ):
                return None
        elif "net cash increase" not in facts:
            return None
    if invalid.intersection(used) or any(label not in facts for label in used):
        return None
    inputs = tuple(facts[label] for label in dict.fromkeys(used))
    a, b = (facts[label] for label in (used[0], denominator))
    if a.currency != b.currency or (ratio and b.amount <= 0):
        return None
    numerator_amount = (
        facts["revenue"].amount - facts["COGS"].amount
        if numeric_numerator
        else a.amount
    )
    percentage = ratio and kind != "current ratio"
    value = (
        numerator_amount / b.amount * (100 if percentage else 1)
        if ratio
        else a.amount - b.amount
    )
    places = Decimal("0.001") if kind == "current ratio" else Decimal("0.01")
    value = value.quantize(places, rounding=ROUND_HALF_UP)
    suffix = "%" if percentage else "x" if ratio else f" {a.currency}"
    operator = "/" if ratio else "-"
    formula = f"{expression} {operator} {denominator}" + (
        " * 100" if percentage else ""
    )
    numeric = f"{numeric_numerator or f'{a.amount:f}'} {operator} {b.amount:f}" + (
        " * 100" if percentage else ""
    )
    source_numbers = {fact.source_number for fact in inputs}
    if period:
        # A title/header in another retrieved chunk may establish the year.
        # Cite that evidence as well as both arithmetic input rows.
        source_numbers.add(
            next(
                index
                for index, item in enumerate(evidence, 1)
                if any(
                    match.group("year") == period
                    for match in _PERIOD_CONTEXT.finditer(item.chunk_text)
                )
            )
        )
    sources = tuple(sorted(source_numbers))
    citations = " ".join(f"[Source {i}]" for i in sources)
    return Calculation(
        f"Derived {kind}{f' for FY{period}' if period else ''}: "
        f"{formula} = {numeric} = {value}{suffix} {citations}.",
        sources,
        inputs,
        period,
    )
