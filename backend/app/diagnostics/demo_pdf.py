"""Generate a clearly fictional financial report for manual acceptance testing."""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

PAGES = (
    (
        "FICTIONAL DEMO - NOT REAL FINANCIAL DATA\n\n"
        "Meridian Analytics Ltd. FY2025 Annual Report\n\n"
        "Total revenue for FY2025 was USD 125.5 million. "
        "Total revenue for FY2024 was USD 100.0 million."
    ),
    (
        "FICTIONAL DEMO - NOT REAL FINANCIAL DATA\n\n"
        "Operating Results\n\n"
        "Operating profit was USD 25.1 million in FY2025 and USD 20.0 million "
        "in FY2024. The FY2025 operating margin was 20.0%. Management attributed "
        "the improvement to subscription growth and lower infrastructure costs."
    ),
    (
        "FICTIONAL DEMO - NOT REAL FINANCIAL DATA\n\n"
        "Risk Factors\n\n"
        "Management identified customer concentration, foreign-exchange volatility, "
        "and cybersecurity incidents as material business risks. This report does "
        "not disclose a debt-to-equity ratio."
    ),
)


def create_demo_pdf(destination: Path) -> Path:
    """Write a three-page fictional report without overwriting an existing file."""

    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    document = pymupdf.open()
    try:
        for content in PAGES:
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(72, 72, 540, 760),
                content,
                fontsize=12,
                lineheight=1.4,
            )
        document.save(destination)
    finally:
        document.close()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("fictional-financial-report.pdf"),
        help="Destination PDF path (must not already exist)",
    )
    args = parser.parse_args()
    created = create_demo_pdf(args.output)
    print(created)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
