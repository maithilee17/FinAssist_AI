"""Safe document-management API schemas."""

from datetime import datetime
from math import ceil
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    file_size: int
    mime_type: str
    page_count: int
    processing_status: DocumentStatus
    processing_error: str | None
    indexed_chunk_count: int
    embedding_model: str | None
    indexed_at: datetime | None
    upload_date: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def build(
        cls, items: list[DocumentResponse], total: int, page: int, page_size: int
    ) -> "DocumentListResponse":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=ceil(total / page_size) if total else 0,
        )


class DocumentStatusResponse(BaseModel):
    id: UUID
    processing_status: DocumentStatus
    processing_error: str | None
    page_count: int
    indexed_chunk_count: int
    embedding_model: str | None
    indexed_at: datetime | None
    updated_at: datetime


class DocumentPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    extracted_text: str
    char_count: int
    is_empty: bool
    extraction_metadata: dict[str, object] = Field(default_factory=dict)


class DocumentPagesResponse(BaseModel):
    document_id: UUID
    filename: str
    items: list[DocumentPageResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
