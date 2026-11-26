"""Authenticated PDF upload, processing, listing, inspection, retry, and deletion APIs."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_db
from app.dependencies import CurrentUser
from app.models.document import Document, DocumentChunk, DocumentPage, DocumentStatus
from app.schemas.document import (
    DocumentListResponse,
    DocumentPagesResponse,
    DocumentResponse,
    DocumentStatusResponse,
)
from app.services.document_processor import (
    build_processing_artifacts,
    chunk_models,
    page_models,
)
from app.services.embedding_service import EmbeddingService
from app.services.indexing_service import DocumentIndexingError, DocumentIndexingService
from app.services.keyword_retrieval import KeywordRetrievalService
from app.services.pdf_processor import PdfProcessingError, inspect_pdf
from app.services.rag_dependencies import (
    get_embedding_service,
    get_keyword_retrieval_service,
    get_vector_store,
)
from app.services.storage_service import (
    EmptyUploadError,
    PrivateDocumentStorage,
    UploadTooLargeError,
)
from app.services.vector_store import ChromaVectorStore, VectorStoreError
from app.utils.security import require_csrf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
storage_service = PrivateDocumentStorage(
    settings.upload_dir,
    max_size_bytes=settings.max_upload_size_bytes,
    read_chunk_bytes=settings.upload_read_chunk_bytes,
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_document_storage() -> PrivateDocumentStorage:
    return storage_service


Storage = Annotated[PrivateDocumentStorage, Depends(get_document_storage)]
Embedding = Annotated[EmbeddingService, Depends(get_embedding_service)]
VectorStore = Annotated[ChromaVectorStore, Depends(get_vector_store)]
KeywordRetrieval = Annotated[
    KeywordRetrievalService, Depends(get_keyword_retrieval_service)
]

ALLOWED_PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}


def _safe_display_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=422, detail="A PDF filename is required")
    normalized = filename.replace("\\", "/").split("/")[-1].replace("\x00", "").strip()
    if not normalized or len(normalized) > 255:
        raise HTTPException(
            status_code=422, detail="The PDF filename is invalid or too long"
        )
    if Path(normalized).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only .pdf files are accepted")
    return normalized


async def _owned_document(
    db: AsyncSession, document_id: UUID, user_id: UUID
) -> Document:
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


async def _mark_failed(db: AsyncSession, document_id: UUID, message: str) -> Document:
    await db.rollback()
    document = await db.get(Document, document_id)
    if document is None:
        raise RuntimeError("Document disappeared while processing")
    document.processing_status = DocumentStatus.FAILED
    document.processing_error = message[:1000]
    await db.commit()
    await db.refresh(document)
    return document


async def _index_document(
    db: AsyncSession,
    document: Document,
    chunks: list[DocumentChunk],
    embedding: EmbeddingService,
    vector_store: ChromaVectorStore,
    keyword_retrieval: KeywordRetrievalService,
) -> Document:
    keyword_retrieval.invalidate_user(document.user_id)
    document.processing_status = DocumentStatus.INDEXING
    document.processing_error = None
    document.indexed_chunk_count = 0
    document.embedding_model = embedding.model_name
    document.indexed_at = None
    await db.commit()
    await db.refresh(document)
    try:
        indexed_count = await run_in_threadpool(
            DocumentIndexingService(embedding, vector_store).index_document,
            document,
            chunks,
        )
    except DocumentIndexingError as exc:
        logger.exception(
            "Document indexing failed document=%s user=%s stage=%s",
            document.id,
            document.user_id,
            exc.stage,
        )
        return await _mark_failed(db, document.id, str(exc))
    except Exception:
        logger.exception("Unexpected indexing failure for %s", document.id)
        return await _mark_failed(
            db, document.id, "Document indexing failed unexpectedly"
        )

    document = await db.get(Document, document.id)
    if document is None:
        raise RuntimeError("Document disappeared after indexing")
    document.indexed_chunk_count = indexed_count
    document.embedding_model = embedding.model_name
    document.indexed_at = datetime.now(UTC)
    document.processing_status = DocumentStatus.COMPLETED
    document.processing_error = None
    await db.commit()
    await db.refresh(document)
    return document


async def _process_document(
    db: AsyncSession,
    document: Document,
    storage: PrivateDocumentStorage,
    embedding: EmbeddingService,
    vector_store: ChromaVectorStore,
    keyword_retrieval: KeywordRetrievalService,
) -> Document:
    document.processing_status = DocumentStatus.PROCESSING
    document.processing_error = None
    await db.commit()
    await db.refresh(document)

    try:
        artifacts = await run_in_threadpool(
            build_processing_artifacts,
            document,
            storage.resolve(document.storage_path),
            target_size=settings.chunk_size_tokens,
            overlap_size=settings.chunk_overlap_tokens,
        )
    except PdfProcessingError as exc:
        return await _mark_failed(db, document.id, str(exc))
    except Exception:
        logger.exception("Document extraction failed for %s", document.id)
        return await _mark_failed(
            db, document.id, "Document processing failed unexpectedly"
        )

    persisted_chunks = chunk_models(artifacts)
    try:
        await db.execute(
            delete(DocumentPage).where(DocumentPage.document_id == document.id)
        )
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        db.add_all(page_models(artifacts))
        db.add_all(persisted_chunks)
        document.page_count = artifacts.extraction.page_count
        document.processing_status = DocumentStatus.INDEXING
        document.processing_error = None
        document.indexed_chunk_count = 0
        document.embedding_model = embedding.model_name
        document.indexed_at = None
        await db.commit()
    except Exception:
        logger.exception("Unable to persist extracted chunks for %s", document.id)
        return await _mark_failed(
            db, document.id, "Extracted document data could not be saved"
        )
    return await _index_document(
        db,
        document,
        persisted_chunks,
        embedding,
        vector_store,
        keyword_retrieval,
    )


@router.post(
    "/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
    embedding: Embedding,
    vector_store: VectorStore,
    keyword_retrieval: KeywordRetrieval,
    file: Annotated[UploadFile, File(description="Financial PDF document")],
) -> Document:
    require_csrf(request)
    filename = _safe_display_filename(file.filename)
    mime_type = (file.content_type or "").lower().strip()
    if mime_type not in ALLOWED_PDF_MIME_TYPES:
        await file.close()
        raise HTTPException(
            status_code=415, detail="The uploaded file must have a PDF MIME type"
        )

    document_id = uuid4()
    relative_path = storage.relative_path(current_user.id, document_id)
    try:
        file_size = await storage.save_upload(file, relative_path)
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except EmptyUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("Unable to store uploaded PDF")
        raise HTTPException(
            status_code=500, detail="The PDF could not be stored"
        ) from exc

    try:
        page_count = await run_in_threadpool(
            inspect_pdf, storage.resolve(relative_path)
        )
    except PdfProcessingError as exc:
        storage.remove(relative_path)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    document = Document(
        id=document_id,
        user_id=current_user.id,
        filename=filename,
        storage_path=relative_path,
        file_size=file_size,
        mime_type=mime_type,
        page_count=page_count,
        processing_status=DocumentStatus.UPLOADED,
    )
    db.add(document)
    try:
        await db.commit()
        await db.refresh(document)
    except SQLAlchemyError as exc:
        await db.rollback()
        storage.remove(relative_path)
        logger.exception("Unable to create document metadata")
        raise HTTPException(
            status_code=500, detail="Document metadata could not be saved"
        ) from exc

    return await _process_document(
        db,
        document,
        storage,
        embedding,
        vector_store,
        keyword_retrieval,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DocumentListResponse:
    filters = (Document.user_id == current_user.id,)
    total = await db.scalar(select(func.count(Document.id)).where(*filters)) or 0
    documents = list(
        (
            await db.scalars(
                select(Document)
                .where(*filters)
                .order_by(Document.upload_date.desc(), Document.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    items = [DocumentResponse.model_validate(document) for document in documents]
    return DocumentListResponse.build(items, total, page, page_size)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID, current_user: CurrentUser, db: DbSession
) -> Document:
    return await _owned_document(db, document_id, current_user.id)


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: UUID, current_user: CurrentUser, db: DbSession
) -> DocumentStatusResponse:
    document = await _owned_document(db, document_id, current_user.id)
    return DocumentStatusResponse.model_validate(document, from_attributes=True)


@router.get("/{document_id}/pages", response_model=DocumentPagesResponse)
async def get_document_pages(
    document_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DocumentPagesResponse:
    document = await _owned_document(db, document_id, current_user.id)
    total = (
        await db.scalar(
            select(func.count(DocumentPage.id)).where(
                DocumentPage.document_id == document.id
            )
        )
        or 0
    )
    pages = list(
        (
            await db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == document.id)
                .order_by(DocumentPage.page_number)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return DocumentPagesResponse(
        document_id=document.id,
        filename=document.filename,
        items=pages,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=((total + page_size - 1) // page_size) if total else 0,
    )


@router.post("/{document_id}/retry", response_model=DocumentResponse)
async def retry_document(
    document_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
    embedding: Embedding,
    vector_store: VectorStore,
    keyword_retrieval: KeywordRetrieval,
) -> Document:
    require_csrf(request)
    document = await _owned_document(db, document_id, current_user.id)
    if document.processing_status != DocumentStatus.FAILED:
        raise HTTPException(
            status_code=409, detail="Only failed documents can be retried"
        )
    if not storage.resolve(document.storage_path).is_file():
        raise HTTPException(
            status_code=409, detail="The original PDF is no longer available"
        )
    chunks = list(
        (
            await db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            )
        ).all()
    )
    if chunks:
        return await _index_document(
            db,
            document,
            chunks,
            embedding,
            vector_store,
            keyword_retrieval,
        )
    return await _process_document(
        db,
        document,
        storage,
        embedding,
        vector_store,
        keyword_retrieval,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
    vector_store: VectorStore,
    keyword_retrieval: KeywordRetrieval,
) -> Response:
    require_csrf(request)
    document = await _owned_document(db, document_id, current_user.id)
    try:
        ticket = storage.prepare_delete(document.storage_path)
    except (OSError, ValueError) as exc:
        logger.exception("Unable to quarantine document %s", document.id)
        raise HTTPException(
            status_code=500, detail="Document deletion could not be prepared"
        ) from exc

    try:
        await run_in_threadpool(
            vector_store.delete_document_chunks, current_user.id, document.id
        )
    except VectorStoreError as exc:
        storage.restore_delete(ticket)
        raise HTTPException(
            status_code=503,
            detail="Document vectors could not be removed; deletion was cancelled",
        ) from exc

    try:
        await db.delete(document)
        await db.commit()
        keyword_retrieval.invalidate_user(current_user.id)
    except SQLAlchemyError as exc:
        await db.rollback()
        storage.restore_delete(ticket)
        raise HTTPException(status_code=500, detail="Document deletion failed") from exc

    if not storage.finalize_delete(ticket):
        logger.warning(
            "Quarantined file cleanup remains pending for document %s", document.id
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
