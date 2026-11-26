"""Build and persist page/chunk artifacts for a validated document."""

from dataclasses import dataclass
from pathlib import Path

from app.models.document import Document, DocumentChunk, DocumentPage
from app.services.pdf_processor import PdfExtractionResult, extract_pdf_pages
from app.services.text_chunker import TextChunk, chunk_pages


@dataclass(frozen=True, slots=True)
class ProcessingArtifacts:
    extraction: PdfExtractionResult
    chunks: list[TextChunk]


def build_processing_artifacts(
    document: Document,
    source_path: Path,
    *,
    target_size: int,
    overlap_size: int,
) -> ProcessingArtifacts:
    extraction = extract_pdf_pages(source_path, document.id, document.filename)
    chunks = chunk_pages(
        extraction.pages,
        document_id=document.id,
        user_id=document.user_id,
        target_size=target_size,
        overlap_size=overlap_size,
    )
    return ProcessingArtifacts(extraction=extraction, chunks=chunks)


def page_models(artifacts: ProcessingArtifacts) -> list[DocumentPage]:
    return [
        DocumentPage(
            document_id=page.document_id,
            page_number=page.page_number,
            extracted_text=page.extracted_text,
            char_count=len(page.extracted_text),
            is_empty=not bool(page.extracted_text),
            extraction_metadata=page.metadata,
        )
        for page in artifacts.extraction.pages
    ]


def chunk_models(artifacts: ProcessingArtifacts) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            user_id=chunk.user_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            token_count=chunk.token_count,
            page_numbers=chunk.page_numbers,
        )
        for chunk in artifacts.chunks
    ]
