"""Deterministic extraction and aggregation for the Financial Analytics Dashboard."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.schemas.dashboard import (
    FinancialDashboardResponse,
    FinancialSummarySection,
    MarginTrendPoint,
    MetricCard,
    ProfitabilityTrendPoint,
    RevenueTrendPoint,
)

METRIC_ALIASES = {
    "revenue": (
        "revenue",
        "total revenue",
        "sales",
        "turnover",
        "revenue from operations",
        "total sales",
    ),
    "cost_of_sales": (
        "cost of sales",
        "cost of goods sold",
        "cost of goods sold (cogs)",
        "cogs",
    ),
    "gross_profit": ("gross profit", "gross margin"),
    "net_income": ("net income", "net profit"),
    "operating_income": ("operating income", "operating profit"),
    "total_assets": ("total assets",),
    "total_liabilities": ("total liabilities",),
    "operating_cash_flow": (
        "operating cash flow",
        "net cash from operating activities",
        "net cash provided by operating activities",
    ),
    "investing_cash_flow": (
        "investing cash flow",
        "net cash from investing activities",
        "net cash used in investing activities",
    ),
    "financing_cash_flow": (
        "financing cash flow",
        "net cash from financing activities",
        "net cash used in financing activities",
    ),
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "CAD": "CA$",
    "AUD": "A$",
}


def _match_metric(label: str) -> str | None:
    normalized = " ".join(label.lower().split())
    for metric, aliases in METRIC_ALIASES.items():
        if any(
            normalized == a or normalized.startswith(a + " ") or normalized.endswith(" " + a)
            for a in aliases
        ):
            return metric
    return None


def _format_currency_compact(amount: Decimal, currency: str | None) -> str:
    sym = CURRENCY_SYMBOLS.get(currency or "", (currency + " ") if currency else "$")
    abs_amt = abs(amount)
    sign = "-" if amount < 0 else ""
    if abs_amt >= Decimal("1000000000"):
        val = abs_amt / Decimal("1000000000")
        return f"{sign}{sym}{val:,.2f}B"
    if abs_amt >= Decimal("1000000"):
        val = abs_amt / Decimal("1000000")
        return f"{sign}{sym}{val:,.2f}M"
    if abs_amt >= Decimal("1000"):
        val = abs_amt / Decimal("1000")
        return f"{sign}{sym}{val:,.0f}K"
    return f"{sign}{sym}{abs_amt:,.2f}"


def _format_currency_full(amount: Decimal, currency: str | None) -> str:
    sym = CURRENCY_SYMBOLS.get(currency or "", (currency + " ") if currency else "$")
    sign = "-" if amount < 0 else ""
    abs_amt = abs(amount)
    return f"{sign}{sym}{abs_amt:,.2f}"


def _format_percentage(val: Decimal) -> str:
    return f"{val:,.2f}%"


def build_financial_dashboard(
    document_id: UUID,
    filename: str,
    pages_data: list[dict[str, Any]],
) -> FinancialDashboardResponse:
    """Extract and aggregate financial metrics for the dashboard from document pages."""

    warnings: list[str] = []
    company_name: str | None = None
    currency: str | None = None
    scale_multiplier: Decimal = Decimal(1)
    citations_set: set[str] = set()

    # Year -> Metric -> Fact dict
    facts_by_year: dict[str, dict[str, dict[str, Any]]] = {}

    for page in pages_data:
        page_num = page.get("page_number", 1)
        metadata = page.get("extraction_metadata") or {}
        tables = metadata.get("financial_tables", [])
        page_warnings = metadata.get("table_warnings", [])
        warnings.extend(page_warnings)

        for table in tables:
            t_status = table.get("status", "certain")
            if t_status == "uncertain":
                warnings.append(f"Table on page {page_num} marked uncertain")

            t_warnings = table.get("warnings", [])
            warnings.extend(t_warnings)

            entity = table.get("entity_context", "")
            if entity and not company_name:
                company_lines = [l.strip() for l in entity.splitlines() if l.strip()]
                if company_lines:
                    company_name = company_lines[0]

            columns = table.get("columns", [])
            rows = table.get("rows", [])

            for col in columns:
                if col.get("role") != "value":
                    continue

                col_idx = col.get("index")
                col_period = col.get("period")
                if not col_period:
                    # Try to extract year from header_path
                    header_str = " ".join(col.get("header_path", []))
                    ym = re.search(r"(?:19|20)\d{2}", header_str)
                    if ym:
                        col_period = ym.group(0)

                if not col_period:
                    continue

                year_match = re.search(r"(?:19|20)\d{2}", str(col_period))
                if not year_match:
                    continue
                year = year_match.group(0)

                col_curr = col.get("currency")
                if col_curr and not currency:
                    currency = col_curr

                col_mult_raw = col.get("multiplier", 1)
                try:
                    col_mult = Decimal(str(col_mult_raw))
                    if col_mult > 1 and scale_multiplier == Decimal(1):
                        scale_multiplier = col_mult
                except (InvalidOperation, TypeError):
                    col_mult = Decimal(1)

                table_title = table.get("title", "Financial Statement")
                citations_set.add(f"[Source 1] Page {page_num}: {table_title}")

                period_facts = facts_by_year.setdefault(year, {})

                for row in rows:
                    raw_label = row.get("label", "")
                    metric = _match_metric(raw_label)
                    if not metric:
                        continue

                    cells = row.get("cells", [])
                    if col_idx is None or col_idx >= len(cells):
                        continue

                    cell = cells[col_idx]
                    cell_val = cell.get("value")
                    if cell_val is None:
                        continue

                    try:
                        amt = Decimal(str(cell_val))
                    except (InvalidOperation, TypeError):
                        continue

                    # If cost of sales is negative in the raw table, normalize to positive magnitude
                    if metric == "cost_of_sales":
                        amt = abs(amt)

                    # Store if not already present or higher precision
                    if metric not in period_facts:
                        period_facts[metric] = {
                            "amount": amt,
                            "raw": cell.get("raw"),
                            "page": page_num,
                            "currency": cell.get("currency") or col_curr or currency,
                            "multiplier": col_mult,
                        }

    # If no facts found, return empty dashboard response
    if not facts_by_year:
        return FinancialDashboardResponse(
            document_id=document_id,
            filename=filename,
            company_name=company_name,
            currency=currency,
            has_financial_data=False,
            message="No structured financial statements or multi-period tables were detected in this document.",
            warnings=list(sorted(set(warnings))),
        )

    # Sort available fiscal years chronologically
    available_years = sorted(facts_by_year.keys(), key=lambda y: int(y))

    # Reconcile Gross Profit and compute margins per year
    for year in available_years:
        facts = facts_by_year[year]
        rev = facts.get("revenue", {}).get("amount")
        cogs = facts.get("cost_of_sales", {}).get("amount")
        gp = facts.get("gross_profit", {}).get("amount")
        ni = facts.get("net_income", {}).get("amount")
        op = facts.get("operating_income", {}).get("amount")

        # Derive Gross Profit if absent but Revenue & Cost of Sales are present
        if gp is None and rev is not None and cogs is not None:
            gp = rev - cogs
            facts["gross_profit"] = {
                "amount": gp,
                "raw": str(gp),
                "page": facts["revenue"]["page"],
                "currency": facts["revenue"].get("currency"),
                "multiplier": facts["revenue"].get("multiplier", Decimal(1)),
                "derived": True,
            }

        # Calculate Margins
        if rev is not None and rev > Decimal(0):
            if gp is not None:
                gp_margin = ((gp / rev) * Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                facts["gross_profit_margin"] = {"amount": gp_margin}

            if ni is not None:
                ni_margin = ((ni / rev) * Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                facts["net_profit_margin"] = {"amount": ni_margin}

            if op is not None:
                op_margin = ((op / rev) * Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                facts["operating_margin"] = {"amount": op_margin}

    # Calculate YoY Growth across sorted periods
    yoy_growth: dict[str, dict[str, Decimal]] = {}
    for i in range(1, len(available_years)):
        prev_yr = available_years[i - 1]
        curr_yr = available_years[i]
        curr_facts = facts_by_year[curr_yr]
        prev_facts = facts_by_year[prev_yr]

        growth_dict = {}
        for m in ("revenue", "gross_profit", "net_income", "operating_income"):
            curr_val = curr_facts.get(m, {}).get("amount")
            prev_val = prev_facts.get(m, {}).get("amount")
            if curr_val is not None and prev_val is not None and prev_val != Decimal(0):
                pct = (((curr_val - prev_val) / abs(prev_val)) * Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                growth_dict[m] = pct
        yoy_growth[curr_yr] = growth_dict

    # Determine Scale Name
    scale_name: str | None = None
    if scale_multiplier == Decimal(1000):
        scale_name = "thousands"
    elif scale_multiplier == Decimal(1000000):
        scale_name = "millions"
    elif scale_multiplier == Decimal(1000000000):
        scale_name = "billions"

    # Build KPI Cards for Latest Fiscal Year
    latest_year = available_years[-1]
    latest_facts = facts_by_year[latest_year]
    latest_growth = yoy_growth.get(latest_year, {})

    kpi_cards: list[MetricCard] = []

    # 1. Total Revenue Card
    rev_fact = latest_facts.get("revenue")
    if rev_fact:
        rev_val = rev_fact["amount"]
        rev_yoy = latest_growth.get("revenue")
        kpi_cards.append(
            MetricCard(
                label="Total Revenue",
                value=float(rev_val),
                formatted_value=_format_currency_compact(rev_val, currency),
                currency=currency,
                scale=scale_name,
                period=f"FY{latest_year}",
                yoy_change=float(rev_yoy) if rev_yoy is not None else None,
                yoy_change_formatted=f"{rev_yoy:+,.2f}%" if rev_yoy is not None else None,
                source_citation=f"Page {rev_fact.get('page')}",
            )
        )
    else:
        kpi_cards.append(
            MetricCard(
                label="Total Revenue",
                value=None,
                formatted_value="Not available",
                currency=currency,
                period=f"FY{latest_year}",
            )
        )

    # 2. Gross Profit Card
    gp_fact = latest_facts.get("gross_profit")
    if gp_fact:
        gp_val = gp_fact["amount"]
        gp_yoy = latest_growth.get("gross_profit")
        kpi_cards.append(
            MetricCard(
                label="Gross Profit",
                value=float(gp_val),
                formatted_value=_format_currency_compact(gp_val, currency),
                currency=currency,
                scale=scale_name,
                period=f"FY{latest_year}",
                yoy_change=float(gp_yoy) if gp_yoy is not None else None,
                yoy_change_formatted=f"{gp_yoy:+,.2f}%" if gp_yoy is not None else None,
                source_citation=f"Page {gp_fact.get('page')}",
            )
        )
    else:
        kpi_cards.append(
            MetricCard(
                label="Gross Profit",
                value=None,
                formatted_value="Not available",
                currency=currency,
                period=f"FY{latest_year}",
            )
        )

    # 3. Gross Profit Margin Card
    gpm_fact = latest_facts.get("gross_profit_margin")
    if gpm_fact:
        gpm_val = gpm_fact["amount"]
        # YoY difference in margin points
        prev_year = available_years[-2] if len(available_years) >= 2 else None
        prev_gpm = facts_by_year.get(prev_year or "", {}).get("gross_profit_margin", {}).get("amount")
        margin_diff = (gpm_val - prev_gpm) if prev_gpm is not None else None

        kpi_cards.append(
            MetricCard(
                label="Gross Margin",
                value=float(gpm_val),
                formatted_value=_format_percentage(gpm_val),
                period=f"FY{latest_year}",
                yoy_change=float(margin_diff) if margin_diff is not None else None,
                yoy_change_formatted=f"{margin_diff:+,.2f} pp" if margin_diff is not None else None,
                yoy_change_unit="pp",
                source_citation=f"Derived ({gp_fact.get('page') if gp_fact else latest_facts.get('revenue', {}).get('page')})",
            )
        )
    else:
        kpi_cards.append(
            MetricCard(
                label="Gross Margin",
                value=None,
                formatted_value="Not available",
                period=f"FY{latest_year}",
            )
        )

    # 4. Net Income Card
    ni_fact = latest_facts.get("net_income")
    if ni_fact:
        ni_val = ni_fact["amount"]
        ni_yoy = latest_growth.get("net_income")
        kpi_cards.append(
            MetricCard(
                label="Net Income",
                value=float(ni_val),
                formatted_value=_format_currency_compact(ni_val, currency),
                currency=currency,
                scale=scale_name,
                period=f"FY{latest_year}",
                yoy_change=float(ni_yoy) if ni_yoy is not None else None,
                yoy_change_formatted=f"{ni_yoy:+,.2f}%" if ni_yoy is not None else None,
                source_citation=f"Page {ni_fact.get('page')}",
            )
        )
    else:
        kpi_cards.append(
            MetricCard(
                label="Net Income",
                value=None,
                formatted_value="Not available",
                currency=currency,
                period=f"FY{latest_year}",
            )
        )

    # Optional 5. Operating Income Card (if present)
    op_fact = latest_facts.get("operating_income")
    if op_fact:
        op_val = op_fact["amount"]
        op_yoy = latest_growth.get("operating_income")
        kpi_cards.append(
            MetricCard(
                label="Operating Income",
                value=float(op_val),
                formatted_value=_format_currency_compact(op_val, currency),
                currency=currency,
                scale=scale_name,
                period=f"FY{latest_year}",
                yoy_change=float(op_yoy) if op_yoy is not None else None,
                yoy_change_formatted=f"{op_yoy:+,.2f}%" if op_yoy is not None else None,
                source_citation=f"Page {op_fact.get('page')}",
            )
        )

    # Build Chronological Trend Series
    revenue_trend: list[RevenueTrendPoint] = []
    profitability_trend: list[ProfitabilityTrendPoint] = []
    margin_trend: list[MarginTrendPoint] = []

    for year in available_years:
        facts = facts_by_year[year]
        rev = facts.get("revenue", {}).get("amount")
        gp = facts.get("gross_profit", {}).get("amount")
        ni = facts.get("net_income", {}).get("amount")
        op = facts.get("operating_income", {}).get("amount")
        gpm = facts.get("gross_profit_margin", {}).get("amount")
        npm = facts.get("net_profit_margin", {}).get("amount")
        opm = facts.get("operating_margin", {}).get("amount")

        if rev is not None:
            revenue_trend.append(
                RevenueTrendPoint(
                    period=year,
                    fiscal_year=f"FY{year}",
                    revenue=float(rev),
                    formatted=_format_currency_compact(rev, currency),
                    currency=currency,
                )
            )

        profitability_trend.append(
            ProfitabilityTrendPoint(
                period=year,
                fiscal_year=f"FY{year}",
                gross_profit=float(gp) if gp is not None else None,
                net_income=float(ni) if ni is not None else None,
                operating_income=float(op) if op is not None else None,
                formatted_gross_profit=_format_currency_compact(gp, currency) if gp is not None else None,
                formatted_net_income=_format_currency_compact(ni, currency) if ni is not None else None,
                currency=currency,
            )
        )

        margin_trend.append(
            MarginTrendPoint(
                period=year,
                fiscal_year=f"FY{year}",
                gross_profit_margin=float(gpm) if gpm is not None else None,
                net_profit_margin=float(npm) if npm is not None else None,
                operating_margin=float(opm) if opm is not None else None,
            )
        )

    # Build Grounded Performance Summary
    observations: list[str] = []
    limitations: list[str] = []

    # Revenue Commentary
    if len(available_years) >= 2:
        first_yr = available_years[0]
        first_rev = facts_by_year[first_yr].get("revenue", {}).get("amount")
        last_rev = facts_by_year[latest_year].get("revenue", {}).get("amount")
        latest_rev_growth = yoy_growth.get(latest_year, {}).get("revenue")

        if first_rev and last_rev:
            total_change = (((last_rev - first_rev) / abs(first_rev)) * Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            direction = "increased" if total_change > 0 else "decreased"
            growth_clause = (
                f" with a year-over-year growth rate of {latest_rev_growth:+,.2f}% in FY{latest_year}"
                if latest_rev_growth is not None
                else ""
            )
            rev_summary = (
                f"Total revenue {direction} from {_format_currency_compact(first_rev, currency)} in FY{first_yr} "
                f"to {_format_currency_compact(last_rev, currency)} in FY{latest_year} "
                f"({total_change:+,.2f}% cumulative){growth_clause}."
            )
        else:
            rev_summary = "Revenue figures are partially available across the reported reporting periods."
    else:
        single_rev = facts_by_year[latest_year].get("revenue", {}).get("amount")
        if single_rev:
            rev_summary = (
                f"Total revenue was reported at {_format_currency_compact(single_rev, currency)} for FY{latest_year}."
            )
        else:
            rev_summary = "Revenue data is not reported in this statement."

    # Profitability Commentary
    gp_latest = latest_facts.get("gross_profit", {}).get("amount")
    ni_latest = latest_facts.get("net_income", {}).get("amount")
    gpm_latest = latest_facts.get("gross_profit_margin", {}).get("amount")
    npm_latest = latest_facts.get("net_profit_margin", {}).get("amount")

    prof_parts = []
    if gp_latest is not None:
        prof_parts.append(f"Gross profit reached {_format_currency_compact(gp_latest, currency)}")
        if gpm_latest is not None:
            prof_parts[-1] += f" ({gpm_latest:,.2f}% gross margin)"
    if ni_latest is not None:
        prof_parts.append(f"net income was {_format_currency_compact(ni_latest, currency)}")
        if npm_latest is not None:
            prof_parts[-1] += f" ({npm_latest:,.2f}% net profit margin)"

    if prof_parts:
        prof_summary = f"In FY{latest_year}, {'; '.join(prof_parts)}."
    else:
        prof_summary = "Profitability metrics were not disclosed in the structured statement."

    # Growth Commentary
    if len(available_years) >= 2:
        growth_items = []
        for yr in available_years[1:]:
            g = yoy_growth.get(yr, {})
            rg = g.get("revenue")
            gpg = g.get("gross_profit")
            nig = g.get("net_income")
            if rg is not None:
                growth_items.append(f"FY{yr} revenue grew {rg:+,.2f}%")
            if gpg is not None:
                growth_items.append(f"gross profit shifted {gpg:+,.2f}%")
            if nig is not None:
                growth_items.append(f"net income shifted {nig:+,.2f}%")
        growth_summary = (
            "Year-over-year operational expansion: " + "; ".join(growth_items) + "."
            if growth_items
            else "Year-over-year growth could not be fully reconciled across consecutive fiscal periods."
        )
    else:
        growth_summary = "Multi-year growth rates cannot be calculated because only a single fiscal period is present."

    # Grounded Key Observations
    if len(available_years) >= 2:
        # Check margin trend
        margins = [
            (yr, facts_by_year[yr].get("gross_profit_margin", {}).get("amount"))
            for yr in available_years
            if facts_by_year[yr].get("gross_profit_margin", {}).get("amount") is not None
        ]
        if len(margins) >= 2:
            if all(margins[i][1] > margins[i - 1][1] for i in range(1, len(margins))):
                observations.append(
                    f"Gross profit margin expanded steadily across reporting years ("
                    + " → ".join(f"{m[1]}% in FY{m[0]}" for m in margins)
                    + "), demonstrating improved operational unit economics."
                )
            elif all(margins[i][1] < margins[i - 1][1] for i in range(1, len(margins))):
                observations.append(
                    f"Gross margin contracted across periods ("
                    + " → ".join(f"{m[1]}% in FY{m[0]}" for m in margins)
                    + "), reflecting higher relative production costs."
                )

        # Check revenue vs net income growth
        lat_rev_g = yoy_growth.get(latest_year, {}).get("revenue")
        lat_ni_g = yoy_growth.get(latest_year, {}).get("net_income")
        if lat_rev_g is not None and lat_ni_g is not None:
            if lat_ni_g > lat_rev_g:
                observations.append(
                    f"In FY{latest_year}, net income growth ({lat_ni_g:+,.2f}%) outpaced revenue growth ({lat_rev_g:+,.2f}%), indicating positive operating leverage."
                )
            elif lat_ni_g < lat_rev_g:
                observations.append(
                    f"In FY{latest_year}, revenue increased by {lat_rev_g:+,.2f}% while net income shifted by {lat_ni_g:+,.2f}%, indicating operational overheads expanded faster than top-line sales."
                )

    if not observations:
        observations.append(
            f"All reported financial figures for {company_name or 'the company'} reflect verified table extractions with deterministic Decimal calculations."
        )

    # Limitations
    if len(available_years) < 2:
        limitations.append(
            "Document contains only a single reporting period; longitudinal trend comparisons and growth calculations are withheld."
        )
    if warnings:
        limitations.append(
            "Extraction flags or OCR character warnings are present in table metadata; verify specific figures against original document pages."
        )
    if not latest_facts.get("operating_income"):
        limitations.append(
            "Operating income was not explicitly itemized in the statement table."
        )

    summary_section = FinancialSummarySection(
        revenue_performance=rev_summary,
        profitability=prof_summary,
        growth=growth_summary,
        key_observations=observations,
        limitations=limitations,
        citations=sorted(list(citations_set)),
    )

    return FinancialDashboardResponse(
        document_id=document_id,
        filename=filename,
        company_name=company_name,
        currency=currency,
        scale=scale_name,
        has_financial_data=True,
        available_years=available_years,
        kpi_cards=kpi_cards,
        revenue_trend=revenue_trend,
        profitability_trend=profitability_trend,
        margin_trend=margin_trend,
        summary=summary_section,
        warnings=sorted(list(set(warnings))),
    )
