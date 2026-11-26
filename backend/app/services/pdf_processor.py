"""Safe page-aware PDF inspection and text extraction with PyMuPDF."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pymupdf

from app.config import get_settings
from app.services.financial_table_extractor import (
    extract_financial_tables,
    narrative_outside_tables,
)
from app.services.ocr_service import OcrService
from app.services.pdf_page_classifier import PageExtractionMode, classify_pdf_page
from app.services.scanned_table_reconstructor import (
    narrative_outside_ocr_tables,
    reconstruct_scanned_financial_tables,
)
from app.services.text_cleaner import clean_extracted_text


class PdfProcessingError(ValueError):
    """Base class for user-safe PDF validation and extraction failures."""


class InvalidPdfError(PdfProcessingError):
    pass


class EncryptedPdfError(PdfProcessingError):
    pass


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    document_id: UUID
    filename: str
    page_number: int
    extracted_text: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PdfExtractionResult:
    document_id: UUID
    filename: str
    page_count: int
    pages: list[ExtractedPage]
    metadata: dict[str, object] = field(default_factory=dict)


def _open_valid_pdf(path: Path) -> pymupdf.Document:
    document: pymupdf.Document | None = None
    try:
        with path.open("rb") as source:
            header = source.read(1024)
        if b"%PDF-" not in header:
            raise InvalidPdfError(
                "The uploaded file does not contain a valid PDF header"
            )

        # Let PyMuPDF page the private server-side file instead of duplicating the
        # complete upload into a Python bytes object. The upload service already
        # resolves a trusted storage path; only the first 1 KiB is read in Python.
        document = _open_path_backed_pdf(path)
        if document is None:
            raise InvalidPdfError("The PDF is corrupted or cannot be read")
        try:
            if not document.is_pdf:
                raise InvalidPdfError("The uploaded file is not a PDF document")
            if document.needs_pass:
                raise EncryptedPdfError(
                    "Encrypted or password-protected PDFs are not supported"
                )
            if document.page_count < 1:
                raise InvalidPdfError("The PDF does not contain any pages")
        except (PdfProcessingError, RuntimeError, ValueError):
            document.close()
            raise
        return document
    except PdfProcessingError:
        raise
    except (
        pymupdf.FileDataError,
        pymupdf.EmptyFileError,
        RuntimeError,
        OSError,
    ) as exc:
        raise InvalidPdfError("The PDF is corrupted or cannot be read") from exc


def _open_path_backed_pdf(path: Path) -> pymupdf.Document | None:
    """Open a PDF without retaining PyMuPDF's failed native stream on Windows.

    Some PyMuPDF releases attach the native file stream to the exception raised
    by ``Document(path)``.  Keeping that exception in the caller's active frame
    can prevent immediate cleanup of a rejected upload on Windows.  This narrow
    helper lets the exception frame be released before the caller deletes the
    private file, while valid PDFs remain path-backed and memory efficient.
    """

    try:
        return pymupdf.open(path)
    except (
        pymupdf.FileDataError,
        pymupdf.EmptyFileError,
        RuntimeError,
        OSError,
    ):
        return None


def inspect_pdf(path: Path) -> int:
    """Validate actual PDF content and return its page count."""

    document = _open_valid_pdf(path)
    try:
        return document.page_count
    finally:
        document.close()


def extract_pdf_pages(
    path: Path, document_id: UUID, filename: str
) -> PdfExtractionResult:
    """Extract sorted text blocks page by page while preserving empty pages and supporting OCR."""

    document = _open_valid_pdf(path)
    pages: list[ExtractedPage] = []
    document_title = ""
    previous_tables = []
    settings = get_settings()
    ocr_service = (
        OcrService(
            language=settings.ocr_language,
            dpi=settings.ocr_dpi,
            max_pixels=settings.ocr_max_page_pixels,
        )
        if settings.ocr_enabled
        else None
    )

    try:
        for index, page in enumerate(document):
            page_num = index + 1
            classification = classify_pdf_page(
                page,
                page_number=page_num,
                dpi=settings.ocr_dpi,
                max_pixels=settings.ocr_max_page_pixels,
            )

            # 1. Native Digital Extraction
            try:
                blocks = page.get_text("blocks", sort=True)
            except (RuntimeError, ValueError) as exc:
                raise InvalidPdfError(
                    f"Text extraction failed on page {page_num}"
                ) from exc

            text_blocks = [
                clean_extracted_text(str(block[4]))
                for block in blocks
                if len(block) >= 7 and int(block[6]) == 0 and str(block[4]).strip()
            ]
            extracted_text = "\n\n".join(block for block in text_blocks if block)
            if index == 0 and extracted_text:
                document_title = next(
                    (line for line in extracted_text.splitlines() if line.strip()), ""
                )

            tables, table_warnings, table_timings = extract_financial_tables(
                page,
                document_id,
                page_num,
                document_title,
            )

            ocr_applied = False
            ocr_words_count = 0
            ocr_time_ms = 0.0
            ocr_preprocessing: list[str] = []
            ocr_result = None

            # 2. OCR Fallback / Enhancement for Scanned, Low Confidence, or Image-Only Pages
            if (
                classification.requires_ocr
                and ocr_service is not None
                and (
                    not tables
                    or classification.mode == PageExtractionMode.IMAGE_ONLY
                    or classification.mode == PageExtractionMode.LOW_TEXT_CONFIDENCE
                )
            ):
                ocr_result = ocr_service.extract_page_ocr(
                    page, page_number=page_num, dpi=settings.ocr_dpi
                )
                ocr_applied = ocr_result.ocr_applied
                ocr_words_count = ocr_result.word_count
                ocr_time_ms = ocr_result.ocr_time_ms
                ocr_preprocessing = ocr_result.preprocessing
                table_warnings.extend(ocr_result.warnings)

                if ocr_applied and ocr_result.text.strip():
                    if index == 0 and not document_title:
                        document_title = next(
                            (line for line in ocr_result.text.splitlines() if line.strip()), ""
                        )

                    # Reconstruct tables from OCR words if no digital tables were found
                    if not tables:
                        scanned_tables = reconstruct_scanned_financial_tables(
                            ocr_result.words,
                            document_id,
                            page_num,
                            document_title,
                        )
                        if scanned_tables:
                            tables = scanned_tables
                            table_timings["scanned_reconstruction_ms"] = ocr_time_ms
                            for st in scanned_tables:
                                table_warnings.extend(st.warnings)

                    # If page had no digital text or was low quality, adopt OCR text
                    if not extracted_text or classification.mode in (
                        PageExtractionMode.IMAGE_ONLY,
                        PageExtractionMode.LOW_TEXT_CONFIDENCE,
                    ):
                        extracted_text = clean_extracted_text(ocr_result.text)

            # 3. Continuation linking (applies to both digital and scanned tables)
            for table in tables:
                if "continued" in table.title.lower():
                    candidates = [
                        prior
                        for prior in previous_tables
                        if prior.title.lower().replace(" (continued)", "")
                        == table.title.lower().replace(" (continued)", "")
                        and [
                            (c.header_path, c.currency, c.multiplier)
                            for c in prior.columns
                        ]
                        == [
                            (c.header_path, c.currency, c.multiplier)
                            for c in table.columns
                        ]
                    ]
                    if len(candidates) == 1:
                        table.continuation_of = candidates[0].table_id
                    else:
                        table.warnings.append("continuation_not_unambiguously_linked")

            accepted = [table for table in tables if table.status == "certain"]
            extra = {
                "financial_tables": [table.model_dump(mode="json") for table in tables],
                "table_warnings": table_warnings,
                "table_timings_ms": table_timings,
                "page_mode": classification.mode.value,
                "ocr_applied": ocr_applied,
                "ocr_words_count": ocr_words_count,
                "ocr_time_ms": ocr_time_ms,
                "ocr_preprocessing": ocr_preprocessing,
            }

            if accepted:
                if ocr_applied and ocr_result is not None and any(t.method.startswith("Tesseract.ocr") for t in accepted):
                    extra["narrative_text"] = clean_extracted_text(
                        narrative_outside_ocr_tables(ocr_result.words, accepted)
                    )
                else:
                    extra["narrative_text"] = clean_extracted_text(
                        narrative_outside_tables(page, accepted)
                    )

            previous_tables = tables
            pages.append(
                ExtractedPage(
                    document_id=document_id,
                    filename=filename,
                    page_number=page_num,
                    extracted_text=extracted_text,
                    metadata={
                        "width": round(float(page.rect.width), 2),
                        "height": round(float(page.rect.height), 2),
                        "text_block_count": len(text_blocks) or (1 if extracted_text else 0),
                        "is_empty": not bool(extracted_text),
                        **extra,
                    },
                )
            )
    finally:
        document.close()

    return PdfExtractionResult(
        document_id=document_id,
        filename=filename,
        page_count=len(pages),
        pages=pages,
        metadata={"format": "PDF", "extractor": "PyMuPDF", "page_count": len(pages)},
    )
