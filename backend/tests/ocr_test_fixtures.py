"""Deterministic, synthetic OCR and scanned financial PDF test fixtures.

Zero LLM-generated truth; authoritative constants match accounting ground truth.
"""

from decimal import Decimal
from pathlib import Path
import pymupdf

SCANNED_INCOME_METRICS = {
    "Revenue": {"2025": Decimal("1200000000"), "2024": Decimal("950000000"), "2023": Decimal("820000000")},
    "Cost of Sales": {"2025": Decimal("780000000"), "2024": Decimal("630000000"), "2023": Decimal("560000000")},
    "Gross Profit": {"2025": Decimal("420000000"), "2024": Decimal("320000000"), "2023": Decimal("260000000")},
    "Operating Income": {"2025": Decimal("160000000"), "2024": Decimal("130000000"), "2023": Decimal("100000000")},
    "Net Income": {"2025": Decimal("91000000"), "2024": Decimal("78000000"), "2023": Decimal("65000000")},
}

SCANNED_BALANCE_METRICS = {
    "Current assets": {"2025": Decimal("360000000")},
    "Current liabilities": {"2025": Decimal("240000000")},
    "Total assets": {"2025": Decimal("900000000")},
    "Total liabilities": {"2025": Decimal("540000000")},
}

SCANNED_CASH_FLOW_METRICS = {
    "Operating cash flow": {"2025": Decimal("135000000")},
    "Investing cash flow": {"2025": Decimal("-90000000")},
    "Financing cash flow": {"2025": Decimal("-25000000")},
}


def create_scanned_income_statement_pdf(
    path: Path,
    dpi: int = 200,
    rotation: int = 0,
    multiplier_text: str = "(Amounts in USD thousands, annual reporting)",
    introduce_conflict: bool = False,
) -> Path:
    """Generate an image-only scanned PDF containing a multi-year income statement."""

    src_doc = pymupdf.open()
    page = src_doc.new_page(width=612, height=792)

    page.insert_text((54, 50), "Apex Global Technologies Inc.", fontsize=14)
    page.insert_text((54, 70), "Consolidated Statements of Income", fontsize=12)
    page.insert_text((54, 88), multiplier_text, fontsize=10)

    headers = ["Financial Metric", "FY2025", "FY2024", "FY2023"]
    gp_2025 = "999,999" if introduce_conflict else "420,000"
    rows = [
        ["Revenue", "1,200,000", "950,000", "820,000"],
        ["Cost of Sales", "780,000", "630,000", "560,000"],
        ["Gross Profit", gp_2025, "320,000", "260,000"],
        ["Operating Income", "160,000", "130,000", "100,000"],
        ["Net Income", "91,000", "78,000", "65,000"],
    ]

    col_x = [54, 280, 380, 480]
    y = 120
    for i, h in enumerate(headers):
        page.insert_text((col_x[i], y), h, fontsize=10)
    page.draw_line((54, y + 6), (560, y + 6), color=(0, 0, 0), width=0.8)

    y += 24
    for row in rows:
        for i, val in enumerate(row):
            page.insert_text((col_x[i], y), val, fontsize=10)
        page.draw_line((54, y + 6), (560, y + 6), color=(0.7, 0.7, 0.7), width=0.4)
        y += 22

    page.insert_textbox(
        pymupdf.Rect(54, y + 16, 560, y + 60),
        "Management commentary: Apex Global Technologies experienced high demand across commercial sectors in FY2025.",
        fontsize=9,
    )

    pix = page.get_pixmap(dpi=dpi)
    src_doc.close()

    scanned_doc = pymupdf.open()
    scanned_page = scanned_doc.new_page(width=612, height=792)
    if rotation in (90, 180, 270):
        scanned_page.set_rotation(rotation)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)

    scanned_doc.save(str(path))
    scanned_doc.close()
    return path


def create_scanned_balance_sheet_pdf(
    path: Path, dpi: int = 200
) -> Path:
    """Generate an image-only scanned balance sheet with single period and currency symbols."""

    src_doc = pymupdf.open()
    page = src_doc.new_page(width=612, height=792)

    page.insert_text((54, 50), "Apex Global Technologies Inc.", fontsize=14)
    page.insert_text((54, 70), "Balance Sheet at 31 December 2025", fontsize=12)
    page.insert_text((54, 88), "Reporting currency: USD in thousands", fontsize=10)

    headers = ["FINANCIAL LINE ITEM", "FY2025 AMOUNT (USD)"]
    rows = [
        ["Current assets", "$360,000"],
        ["Current liabilities", "$240,000"],
        ["Total assets", "$900,000"],
        ["Total liabilities", "$540,000"],
    ]

    col_x = [54, 380]
    y = 120
    for i, h in enumerate(headers):
        page.insert_text((col_x[i], y), h, fontsize=10)
    page.draw_line((54, y + 6), (560, y + 6), color=(0, 0, 0), width=0.8)

    y += 24
    for row in rows:
        for i, val in enumerate(row):
            page.insert_text((col_x[i], y), val, fontsize=10)
        page.draw_line((54, y + 6), (560, y + 6), color=(0.7, 0.7, 0.7), width=0.4)
        y += 22

    pix = page.get_pixmap(dpi=dpi)
    src_doc.close()

    scanned_doc = pymupdf.open()
    scanned_page = scanned_doc.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)

    scanned_doc.save(str(path))
    scanned_doc.close()
    return path


def create_scanned_cash_flow_pdf(
    path: Path, dpi: int = 200
) -> Path:
    """Generate an image-only scanned cash flow statement with negative parenthesized amounts."""

    src_doc = pymupdf.open()
    page = src_doc.new_page(width=612, height=792)

    page.insert_text((54, 50), "Apex Global Technologies Inc.", fontsize=14)
    page.insert_text((54, 70), "Statement of Cash Flows for FY2025", fontsize=12)
    page.insert_text((54, 88), "(USD thousands; consolidated)", fontsize=10)

    headers = ["Cash Flow Activity", "FY2025"]
    rows = [
        ["Operating cash flow", "135,000"],
        ["Investing cash flow", "(90,000)"],
        ["Financing cash flow", "(25,000)"],
    ]

    col_x = [54, 400]
    y = 120
    for i, h in enumerate(headers):
        page.insert_text((col_x[i], y), h, fontsize=10)
    page.draw_line((54, y + 6), (560, y + 6), color=(0, 0, 0), width=0.8)

    y += 24
    for row in rows:
        for i, val in enumerate(row):
            page.insert_text((col_x[i], y), val, fontsize=10)
        page.draw_line((54, y + 6), (560, y + 6), color=(0.7, 0.7, 0.7), width=0.4)
        y += 22

    pix = page.get_pixmap(dpi=dpi)
    src_doc.close()

    scanned_doc = pymupdf.open()
    scanned_page = scanned_doc.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)

    scanned_doc.save(str(path))
    scanned_doc.close()
    return path


def create_mixed_digital_scanned_pdf(
    path: Path, dpi: int = 200
) -> Path:
    """Generate a multi-page PDF with Page 1 digital text and Page 2 scanned image-only."""

    doc = pymupdf.open()

    # Page 1: Digital text
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((54, 60), "Apex Global Technologies - Annual Report FY2025", fontsize=14)
    p1.insert_textbox(
        pymupdf.Rect(54, 90, 550, 300),
        "Apex Global Technologies is an advanced electronics manufacturer founded in 2018.\n\n"
        "The company distributes products through authorized distributor networks worldwide.\n"
        "Key business risks include raw material supply chain fluctuations.",
        fontsize=11,
    )

    # Page 2: Scanned financial table
    src_page = pymupdf.open()
    p2_src = src_page.new_page(width=612, height=792)
    p2_src.insert_text((54, 50), "Apex Global Technologies Inc.", fontsize=14)
    p2_src.insert_text((54, 70), "Consolidated Statements of Income", fontsize=12)
    p2_src.insert_text((54, 88), "(Amounts in USD thousands, annual reporting)", fontsize=10)

    headers = ["Financial Metric", "FY2025", "FY2024", "FY2023"]
    rows = [
        ["Revenue", "1,200,000", "950,000", "820,000"],
        ["Cost of Sales", "780,000", "630,000", "560,000"],
        ["Gross Profit", "420,000", "320,000", "260,000"],
        ["Net Income", "91,000", "78,000", "65,000"],
    ]
    col_x = [54, 280, 380, 480]
    y = 120
    for i, h in enumerate(headers):
        p2_src.insert_text((col_x[i], y), h, fontsize=10)
    y += 24
    for row in rows:
        for i, val in enumerate(row):
            p2_src.insert_text((col_x[i], y), val, fontsize=10)
        y += 22

    pix = p2_src.get_pixmap(dpi=dpi)
    src_page.close()

    p2 = doc.new_page(width=612, height=792)
    p2.insert_image(p2.rect, pixmap=pix)

    doc.save(str(path))
    doc.close()
    return path


def create_oversized_pixel_bomb_pdf(path: Path) -> Path:
    """Generate a PDF page whose dimensions exceed maximum allowed OCR rasterization pixels."""

    doc = pymupdf.open()
    # 6000 x 6000 pt at 200 DPI = ~277 million pixels (> 25 MP limit)
    page = doc.new_page(width=6000, height=6000)
    page.insert_text((100, 100), "Extreme dimension page test", fontsize=24)
    doc.save(str(path))
    doc.close()
    return path
