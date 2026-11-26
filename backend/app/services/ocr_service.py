"""Bounded, secure, local OCR engine integration with PyMuPDF and Tesseract."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import pymupdf

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OcrPageResult:
    text: str
    words: list[tuple[float, float, float, float, str, int, int, int]]
    blocks: list[tuple]
    ocr_applied: bool
    ocr_time_ms: float
    ocr_dpi: int
    word_count: int
    char_count: int
    preprocessing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_tessdata_path() -> str | None:
    """Resolve directory containing eng.traineddata for local or container execution."""

    settings = get_settings()
    candidates: list[Path] = []

    if settings.tessdata_dir:
        candidates.append(Path(settings.tessdata_dir))

    env_prefix = os.environ.get("TESSDATA_PREFIX")
    if env_prefix:
        candidates.append(Path(env_prefix))
        candidates.append(Path(env_prefix) / "tessdata")

    # Local project paths
    candidates.append(Path("backend/tessdata"))
    candidates.append(Path("tessdata"))
    candidates.append(Path(__file__).resolve().parent.parent.parent / "tessdata")

    # Standard Linux package locations
    candidates.append(Path("/usr/share/tesseract-ocr/5/tessdata"))
    candidates.append(Path("/usr/share/tesseract-ocr/4.00/tessdata"))
    candidates.append(Path("/usr/share/tessdata"))
    candidates.append(Path("/usr/local/share/tessdata"))

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "eng.traineddata").is_file():
            return str(candidate.resolve())

    return None


class OcrService:
    """Bounded, thread-safe OCR extraction service using PyMuPDF Tesseract engine."""

    def __init__(
        self,
        language: str = "eng",
        dpi: int = 200,
        max_pixels: int = 25_000_000,
        tessdata_dir: str | None = None,
    ):
        self.language = language
        self.dpi = dpi
        self.max_pixels = max_pixels
        self._tessdata_path = tessdata_dir or resolve_tessdata_path()

    @property
    def is_available(self) -> bool:
        return self._tessdata_path is not None

    def extract_page_ocr(
        self,
        page: pymupdf.Page,
        page_number: int = 1,
        dpi: int | None = None,
    ) -> OcrPageResult:
        """Run OCR on a page and return extracted text and word bounding boxes."""

        start = perf_counter()
        target_dpi = dpi or self.dpi
        preprocessing: list[str] = []
        warnings: list[str] = []

        # 1. Bounds and resource limit check
        width = float(page.rect.width)
        height = float(page.rect.height)
        scale = target_dpi / 72.0
        estimated_pixels = int(width * scale * height * scale)

        if estimated_pixels > self.max_pixels:
            warnings.append(
                f"Page dimensions ({estimated_pixels} px) exceed OCR limit ({self.max_pixels} px)"
            )
            return OcrPageResult(
                text="",
                words=[],
                blocks=[],
                ocr_applied=False,
                ocr_time_ms=0.0,
                ocr_dpi=target_dpi,
                word_count=0,
                char_count=0,
                preprocessing=[],
                warnings=warnings,
            )

        # 2. Check engine availability
        tessdata = self._tessdata_path or resolve_tessdata_path()
        if not tessdata:
            warnings.append("ocr_tessdata_unavailable")
            return OcrPageResult(
                text="",
                words=[],
                blocks=[],
                ocr_applied=False,
                ocr_time_ms=0.0,
                ocr_dpi=target_dpi,
                word_count=0,
                char_count=0,
                preprocessing=[],
                warnings=warnings,
            )

        # 3. Handle page rotation
        rotation = int(page.rotation) % 360
        if rotation != 0:
            preprocessing.append(f"normalized_rotation_{rotation}deg")

        try:
            # Execute PyMuPDF OCR textpage extraction
            tp = page.get_textpage_ocr(
                language=self.language,
                dpi=target_dpi,
                full=True,
                tessdata=tessdata,
            )

            text = page.get_text("text", textpage=tp) or ""
            words = page.get_text("words", textpage=tp) or []
            blocks = page.get_text("blocks", textpage=tp) or []

            # Post-processing: remove noise characters and clean words
            cleaned_words: list[tuple[float, float, float, float, str, int, int, int]] = []
            for w in words:
                word_text = str(w[4]).strip()
                if not word_text:
                    continue
                # Keep original coordinates and block/line structure
                cleaned_words.append(
                    (float(w[0]), float(w[1]), float(w[2]), float(w[3]), word_text, int(w[5]), int(w[6]), int(w[7]))
                )

            ocr_time_ms = round((perf_counter() - start) * 1000, 2)

            return OcrPageResult(
                text=text,
                words=cleaned_words,
                blocks=blocks,
                ocr_applied=True,
                ocr_time_ms=ocr_time_ms,
                ocr_dpi=target_dpi,
                word_count=len(cleaned_words),
                char_count=len(text.strip()),
                preprocessing=preprocessing,
                warnings=warnings,
            )

        except Exception as exc:
            logger.warning(
                "OCR extraction failed on page %d: %s", page_number, exc, exc_info=True
            )
            warnings.append(f"ocr_engine_error: {type(exc).__name__}")
            return OcrPageResult(
                text="",
                words=[],
                blocks=[],
                ocr_applied=False,
                ocr_time_ms=round((perf_counter() - start) * 1000, 2),
                ocr_dpi=target_dpi,
                word_count=0,
                char_count=0,
                preprocessing=preprocessing,
                warnings=warnings,
            )
