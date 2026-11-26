"""Deterministic, hand-authored digital PDF fixtures; no AI-generated truth."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

import pymupdf

INCOME = [
    ["Revenue", "1,200,000", "950,000", "820,000"],
    ["Cost of Sales", "780,000", "630,000", "560,000"],
    ["Gross Profit", "420,000", "320,000", "260,000"],
    ["Net Income", "91,000", "78,000", "65,000"],
    ["Operating Income", "160,000", "130,000", "100,000"],
]
BALANCE = [
    ["Total Assets", "900,000", "800,000"],
    ["Total Liabilities", "540,000", "440,000"],
]
CASH = [
    ["Operating cash flow", "135,000"],
    ["Investing cash flow", "(90,000)"],
    ["Financing cash flow", "(25,000)"],
]


def page_table(
    pdf,
    title,
    headers,
    rows,
    context="USD; annual financial statements",
    merged=False,
    footnote="",
    narrative=True,
):
    page = pdf.new_page()
    page.insert_text((45, 38), "Example Industries", fontsize=12)
    page.insert_text((45, 60), title, fontsize=11)
    page.insert_text((45, 80), context, fontsize=9)
    widths = [235] + [270 / (len(headers) - 1)] * (len(headers) - 1)
    y = 110

    def cell(column, y0, text, span=1, height=32):
        x = 45 + sum(widths[:column])
        rect = pymupdf.Rect(x, y0, x + sum(widths[column : column + span]), y0 + height)
        page.draw_rect(rect, color=(0, 0, 0), width=0.6)
        if text:
            page.insert_textbox(
                rect + (4, 5, -4, -2), text, fontsize=8.5, lineheight=1.1
            )

    if merged:
        cell(0, y, "Financial Metric", height=64)
        cell(1, y, "Consolidated actual", span=len(headers) - 1)
        y += 32
        for col in range(1, len(headers)):
            cell(col, y, headers[col])
        y += 32
    else:
        for col, header in enumerate(headers):
            cell(col, y, header)
        y += 32
    for row in rows:
        for col, text in enumerate(row):
            cell(col, y, text)
        y += 32
    if footnote:
        page.insert_textbox(pymupdf.Rect(45, y + 8, 550, y + 60), footnote, fontsize=8)
    if narrative:
        page.insert_textbox(
            pymupdf.Rect(45, y + 70, 550, y + 115),
            "Management commentary: Example Industries manufactures test equipment. "
            "Demand from distributors is the disclosed business risk.",
            fontsize=9,
        )
    page.insert_text(
        (45, 800), "FICTIONAL DEVELOPMENT FIXTURE - NOT REAL FINANCIAL DATA", fontsize=8
    )
    return page


def make_fixture(path: Path, kind: str):
    with pymupdf.open() as pdf:
        if kind in {
            "simple",
            "three_year",
            "merged",
            "missing",
            "footnotes",
            "multiline",
            "multipage",
            "units",
        }:
            rows = [row[:] for row in INCOME]
            headers = ["Financial Metric", "FY2025", "FY2024", "FY2023"]
            context = "USD; annual financial statements"
            if kind == "simple":
                headers = headers[:2]
                rows = [row[:2] for row in rows]
            if kind == "missing":
                rows[0][2] = "-"
                rows[3][3] = "1.200,50"
                rows[2][1] = ""
            if kind == "footnotes":
                rows[0][1] += "*"
            if kind == "multiline":
                rows[0][0] = "Revenue from\noperations"
            if kind == "units":
                context = "USD in thousands; annual financial statements"
                rows = [
                    [r[0]]
                    + [format(Decimal(x.replace(",", "")) / 1000, ".1f") for x in r[1:]]
                    for r in rows
                ]
            note = (
                "* Revenue excludes an exceptional transaction; requires qualification."
                if kind == "footnotes"
                else ""
            )
            page_table(
                pdf,
                "Consolidated Income Statement",
                headers,
                rows[:3] if kind == "multipage" else rows,
                context,
                merged=kind == "merged",
                footnote=note,
            )
            if kind == "multipage":
                page_table(
                    pdf,
                    "Consolidated Income Statement (continued)",
                    headers,
                    rows[3:],
                    context,
                )
        elif kind == "balance":
            page_table(
                pdf,
                "Consolidated Balance Sheet",
                ["Metric", "31 December 2025", "31 December 2024"],
                BALANCE,
                "USD; statement of financial position",
            )
        elif kind == "cash":
            page_table(
                pdf, "Consolidated Cash Flow Statement", ["Metric", "FY2025"], CASH
            )
        elif kind == "forecast":
            page_table(
                pdf,
                "Income Statement",
                ["Metric", "FY2025 Actual", "FY2025 Forecast"],
                [
                    ["Revenue", "1,200,000", "1,500,000"],
                    ["Net Income", "91,000", "100,000"],
                ],
            )
        elif kind == "quarterly":
            page_table(
                pdf,
                "Income Statement",
                ["Metric", "Q1 FY2025", "FY2024 Annual"],
                [["Revenue", "200,000", "950,000"], ["Net Income", "20,000", "78,000"]],
            )
        else:
            raise ValueError(kind)
        pdf.save(path)
    return path


KINDS = (
    "simple",
    "three_year",
    "balance",
    "cash",
    "units",
    "merged",
    "multiline",
    "footnotes",
    "missing",
    "multipage",
    "forecast",
    "quarterly",
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        path = args.output / (kind + ".pdf")
        if path.exists():
            raise FileExistsError(path)
        make_fixture(path, kind)
    (args.output / "ground_truth.json").write_text(
        json.dumps(
            {
                "source": "hand-authored fixture constants; no model-generated values",
                "income": INCOME,
                "balance": BALANCE,
                "cash": CASH,
                "gross_margin_2025": "35.00",
                "net_margin_2024": "8.21",
                "revenue_growth_2024_to_2025": "26.32",
                "operating_margin_2025": "13.33",
                "debt_to_assets_2025": "60.00",
                "net_cash_change_2025": "20000",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
