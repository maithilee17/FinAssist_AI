"""Automatic page-level extraction-mode detection for financial PDFs."""

from dataclasses import dataclass, field
from enum import Enum
import re
import pymupdf


class PageExtractionMode(str, Enum):
    DIGITAL_TEXT = "digital_text"
    IMAGE_ONLY = "image_only"
    MIXED_CONTENT = "mixed_content"
    LOW_TEXT_CONFIDENCE = "low_text_confidence"
    OCR_REQUIRED = "ocr_required"
    OCR_UNSUPPORTED = "ocr_unsupported"


@dataclass(frozen=True, slots=True)
class PageClassification:
    page_number: int
    mode: PageExtractionMode
    requires_ocr: bool
    digital_char_count: int
    text_block_count: int
    image_count: int
    image_area_ratio: float
    character_quality_score: float
    drawing_count: int
    estimated_ocr_pixels: int
    reasons: list[str] = field(default_factory=list)


def classify_pdf_page(
    page: pymupdf.Page,
    page_number: int = 1,
    dpi: int = 200,
    max_pixels: int = 25_000_000,
) -> PageClassification:
    """Analyze page layout signals to determine optimal extraction mode."""

    width = float(page.rect.width)
    height = float(page.rect.height)
    page_area = max(1.0, width * height)

    scale = dpi / 72.0
    estimated_ocr_pixels = int(width * scale * height * scale)

    reasons: list[str] = []

    # 1. Safety & resource limit check
    if estimated_ocr_pixels > max_pixels:
        reasons.append(
            f"Rasterized pixel count ({estimated_ocr_pixels}) exceeds maximum limit ({max_pixels})"
        )
        return PageClassification(
            page_number=page_number,
            mode=PageExtractionMode.OCR_UNSUPPORTED,
            requires_ocr=False,
            digital_char_count=0,
            text_block_count=0,
            image_count=0,
            image_area_ratio=0.0,
            character_quality_score=0.0,
            drawing_count=0,
            estimated_ocr_pixels=estimated_ocr_pixels,
            reasons=reasons,
        )

    # 2. Extract digital text signals
    raw_text = page.get_text("text") or ""
    stripped_text = raw_text.strip()
    digital_char_count = len(stripped_text)

    blocks = page.get_text("blocks") or []
    text_blocks = [
        b
        for b in blocks
        if len(b) >= 7 and int(b[6]) == 0 and str(b[4]).strip()
    ]
    text_block_count = len(text_blocks)

    # Character quality score (ratio of alphanumeric / printable financial chars to total)
    if digital_char_count > 0:
        valid_chars = sum(
            1
            for c in stripped_text
            if c.isalnum() or c in " \t\n.,$€₹£¥%()+-/*:;\"'#&@[]_—–"
        )
        character_quality_score = round(valid_chars / max(1, digital_char_count), 3)
    else:
        character_quality_score = 1.0

    # 3. Vector drawings check
    drawings = page.get_drawings() or []
    drawing_count = len(drawings)

    # 4. Image inspection and coverage calculation
    images = page.get_images(full=True) or []
    image_count = len(images)

    total_image_area = 0.0
    for img_info in images:
        xref = img_info[0]
        try:
            rects = page.get_image_rects(xref)
            for r in rects:
                total_image_area += float(r.width * r.height)
        except Exception:
            pass

    image_area_ratio = round(min(1.0, total_image_area / page_area), 3)

    # 5. Determine Classification Mode
    # Rule A: Image-only scan (no meaningful digital text, significant image coverage)
    if image_count > 0 and image_area_ratio >= 0.40 and digital_char_count < 35 and drawing_count == 0:
        mode = PageExtractionMode.IMAGE_ONLY
        requires_ocr = True
        reasons.append(
            f"Image coverage is {image_area_ratio * 100:.1f}% with negligible digital text ({digital_char_count} chars)"
        )

    # Rule B: Low text confidence (some digital text exists, but contains poor OCR artifacts or corrupted encoding)
    elif digital_char_count > 0 and character_quality_score < 0.50 and image_count > 0:
        mode = PageExtractionMode.LOW_TEXT_CONFIDENCE
        requires_ocr = True
        reasons.append(
            f"Low character quality score ({character_quality_score:.2f}) indicates potential text overlay or corrupted encoding"
        )

    # Rule C: Mixed Content (meaningful digital text alongside substantial raster image/chart)
    elif image_count > 0 and image_area_ratio >= 0.35 and digital_char_count >= 35:
        mode = PageExtractionMode.MIXED_CONTENT
        requires_ocr = True
        reasons.append(
            f"Mixed content: digital text present ({digital_char_count} chars) alongside {image_area_ratio * 100:.1f}% image coverage"
        )

    # Rule D: Digital text page (native selectable text with low image coverage or vector drawings)
    elif digital_char_count >= 35 or (drawing_count > 0 and digital_char_count >= 10):
        mode = PageExtractionMode.DIGITAL_TEXT
        requires_ocr = False
        reasons.append(
            f"Reliable digital text ({digital_char_count} chars, {text_block_count} blocks, {drawing_count} drawings)"
        )

    # Rule E: Short title page or cover page with high character quality
    elif digital_char_count > 0 and character_quality_score >= 0.70 and image_area_ratio < 0.40:
        mode = PageExtractionMode.DIGITAL_TEXT
        requires_ocr = False
        reasons.append(
            f"Short digital text page ({digital_char_count} chars) with high character quality"
        )

    # Rule F: Image present without text and with low coverage
    elif image_count > 0:
        mode = PageExtractionMode.IMAGE_ONLY
        requires_ocr = True
        reasons.append("Page contains images without selectable text")

    # Rule G: Empty page
    else:
        mode = PageExtractionMode.DIGITAL_TEXT
        requires_ocr = False
        reasons.append("Empty digital page with no images or vector tables")

    return PageClassification(
        page_number=page_number,
        mode=mode,
        requires_ocr=requires_ocr,
        digital_char_count=digital_char_count,
        text_block_count=text_block_count,
        image_count=image_count,
        image_area_ratio=image_area_ratio,
        character_quality_score=character_quality_score,
        drawing_count=drawing_count,
        estimated_ocr_pixels=estimated_ocr_pixels,
        reasons=reasons,
    )
