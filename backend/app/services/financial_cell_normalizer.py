"""Lossless financial-cell normalization. Never guess locale, missing cells or FX."""

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CURRENCIES = r"USD|EUR|GBP|INR|CAD|AUD|JPY|CNY|CHF|SGD|HKD"
SCALES = {
    "thousand": 1000,
    "million": 1000000,
    "billion": 1000000000,
    "lakh": 100000,
    "crore": 10000000,
}


class FinancialCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw: str | None
    value: Decimal | None = None
    currency: str | None = None
    multiplier: Decimal = Decimal(1)
    kind: Literal["number", "percentage", "missing", "text", "ambiguous"] = "text"
    warnings: list[str] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)


def financial_context(text: str) -> tuple[str | None, Decimal, list[str]]:
    currencies = set(re.findall(rf"\b(?:{CURRENCIES})\b", text.upper()))
    for phrase, code in [
        ("US dollars", "USD"),
        ("Indian rupees", "INR"),
        ("pounds sterling", "GBP"),
        ("euros", "EUR"),
    ]:
        if phrase.lower() in text.lower():
            currencies.add(code)
    warnings = []
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    if len(currencies) > 1:
        warnings.append("ambiguous_currency_context")
    scales = {
        value
        for name, value in SCALES.items()
        if re.search(rf"\b{name}s?\b", text, re.IGNORECASE)
    }
    if re.search(
        r"(?:\b(?:in|USD|EUR|GBP|INR)\s*['’]?000s?\b|\(['’]000\))", text, re.IGNORECASE
    ):
        scales.add(1000)
    if len(scales) > 1:
        warnings.append("ambiguous_unit_context")
    multiplier = Decimal(next(iter(scales))) if len(scales) == 1 else Decimal(1)
    if re.search(r"\bexcept\b", text, re.IGNORECASE):
        warnings.append("unit_exception_requires_review")
    return currency, multiplier, warnings


def normalize_financial_cell(
    raw: str | None,
    *,
    currency: str | None = None,
    multiplier: Decimal = Decimal(1),
    dash_is_zero: bool = False,
) -> FinancialCell:
    cell = FinancialCell(raw=raw, currency=currency, multiplier=multiplier)
    if (
        raw is None
        or not raw.strip()
        or raw.strip().lower() in {"n/a", "na", "not available", "..", "..."}
    ):
        cell.kind = "missing"
        return cell
    text = raw.replace("\u00a0", " ").replace("\u202f", " ").strip()
    # Repair only a geometrically wrapped, comma-grouped number. Other embedded
    # whitespace remains uncertain rather than joining potentially distinct cells.
    text = re.sub(r",[ \t]*\n[ \t]*(?=[0-9]{3}\b)", ",", text)
    text = text.replace("\u2212", "-")
    if text in {"-", "—", "–"}:
        cell.kind = "number" if dash_is_zero else "missing"
        cell.value = Decimal(0) if dash_is_zero else None
        if not dash_is_zero:
            cell.warnings.append("dash_not_assumed_zero")
        return cell
    suffix = re.search(r"(\*+|[†‡¹²³]+|\[[a-z0-9]+\]|\([a-z]\))$", text, re.IGNORECASE)
    if suffix and re.search(r"\d", text[: suffix.start()]):
        cell.footnotes.append(suffix.group())
        cell.warnings.append("qualified_cell_requires_review")
        text = text[: suffix.start()].rstrip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    percentage = text.endswith("%")
    if percentage:
        text = text[:-1].strip()
        cell.kind, cell.currency, cell.multiplier = "percentage", None, Decimal(1)
    own_currency = re.search(rf"\b(?:{CURRENCIES})\b|[$€£₹¥]", text, re.IGNORECASE)
    if own_currency:
        token = own_currency.group().upper()
        symbols = {"€": "EUR", "£": "GBP", "₹": "INR"}
        if token == "$":
            code = currency if currency in {"USD", "CAD", "AUD", "SGD", "HKD"} else None
        elif token == "¥":
            code = currency if currency in {"JPY", "CNY"} else None
        else:
            code = symbols.get(token, token)
        if code is None:
            cell.warnings.append("ambiguous_currency_symbol")
        elif currency and currency != code:
            cell.warnings.append("conflicting_cell_currency")
        if not percentage:
            cell.currency = code
        text = text[: own_currency.start()] + text[own_currency.end() :]
    own_scale = re.search(
        r"\b(thousand|million|billion|lakh|crore)s?\b", text, re.IGNORECASE
    )
    if own_scale:
        if not percentage:
            cell.multiplier = Decimal(SCALES[own_scale.group(1).lower()])
        text = text[: own_scale.start()] + text[own_scale.end() :]
    text = text.strip()
    if re.search(r"\s", text):
        cell.kind = "ambiguous" if re.search(r"\d", text) else "text"
        cell.warnings.append("embedded_text_or_unresolved_number_spacing")
        return cell
    if text.startswith("-"):
        if negative:
            cell.kind = "ambiguous"
            cell.warnings.append("multiple_negative_markers")
            return cell
        negative = True
        text = text[1:]
    western = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    indian = r"\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?"
    if not re.fullmatch(western, text) and not (
        cell.currency == "INR" and re.fullmatch(indian, text)
    ):
        cell.kind = "ambiguous" if re.search(r"\d", text) else "text"
        if cell.kind == "ambiguous":
            cell.warnings.append("ambiguous_numeric_format")
        return cell
    if not percentage and re.fullmatch(r"\d{1,3}\.\d{3}", text):
        cell.kind = "ambiguous"
        cell.warnings.append("ambiguous_decimal_or_group_separator")
        return cell
    try:
        value = Decimal(text.replace(",", ""))
        if len(value.as_tuple().digits) + max(cell.multiplier.adjusted(), 0) > 24 or (
            value and value.adjusted() < -24
        ):
            raise InvalidOperation
        cell.value = (-value if negative else value) * cell.multiplier
        cell.kind = "percentage" if percentage else "number"
    except InvalidOperation:
        cell.kind = "ambiguous"
        cell.warnings.append("number_out_of_supported_precision")
    return cell
