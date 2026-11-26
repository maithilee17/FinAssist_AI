"""Authenticated Financial Analytics Dashboard API."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser
from app.models.document import Document, DocumentPage, DocumentStatus
from app.schemas.dashboard import FinancialDashboardResponse
from app.services.financial_dashboard import build_financial_dashboard

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/{document_id}",
    response_model=FinancialDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get financial analytics dashboard data for a document",
)
async def get_document_dashboard(
    document_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> FinancialDashboardResponse:
    """Retrieve verified financial KPI cards, trend charts, and grounded performance summary."""

    # 1. Enforce user ownership & document existence
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied",
        )

    # 2. Check document processing status
    if document.processing_status != DocumentStatus.COMPLETED:
        return FinancialDashboardResponse(
            document_id=document.id,
            filename=document.filename,
            has_financial_data=False,
            message=(
                f"Document processing status is '{document.processing_status.value}'. "
                "Completed indexing is required to view financial analytics."
            ),
        )

    # 3. Retrieve document pages with extraction metadata
    pages_result = await db.execute(
        select(DocumentPage.page_number, DocumentPage.extraction_metadata)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    )
    pages_rows = pages_result.all()

    pages_data = [
        {"page_number": row[0], "extraction_metadata": row[1]}
        for row in pages_rows
    ]

    # 4. Build and return dashboard metrics
    dashboard_data = build_financial_dashboard(
        document_id=document.id,
        filename=document.filename,
        pages_data=pages_data,
    )

    return dashboard_data
