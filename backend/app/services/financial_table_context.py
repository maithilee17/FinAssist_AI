"""Bounded row-group expansion of retrieved tables with relational ownership checks."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.services.financial_table_extractor import decode_table_chunk
from app.services.structured_financial_calculation import table_query
from app.services.vector_store import VectorSearchResult

MAX_CONTEXT_CHUNKS = 16
MAX_CONTEXT_TOKENS = 6000


async def expand_table_context(
    db: AsyncSession,
    question: str,
    results: list[VectorSearchResult],
    *,
    user_id: UUID,
    allowed_document_ids: Sequence[UUID],
) -> list[VectorSearchResult]:
    if not table_query(question, results):
        return results
    seeds = {}
    for item in results:
        table = decode_table_chunk(item.chunk_text)
        if (
            table
            and item.user_id == user_id
            and item.document_id in allowed_document_ids
            and table.document_id == item.document_id
        ):
            seeds[(item.document_id, table.table_id)] = item.similarity_score
    if not seeds or len(seeds) > 4:
        return results
    query = (
        select(DocumentChunk, Document.filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.user_id == user_id,
            DocumentChunk.user_id == user_id,
            Document.id.in_(allowed_document_ids),
            Document.processing_status == DocumentStatus.COMPLETED,
            Document.indexed_chunk_count > 0,
            Document.indexed_at.is_not(None),
            or_(*(DocumentChunk.document_id == doc for doc, _ in seeds)),
            or_(*(DocumentChunk.text.contains(str(table)) for _, table in seeds)),
        )
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        .limit(MAX_CONTEXT_CHUNKS + 1)
    )
    rows = (await db.execute(query)).all()
    if (
        len(rows) > MAX_CONTEXT_CHUNKS
        or sum(row.token_count for row, _ in rows) > MAX_CONTEXT_TOKENS
    ):
        return results  # retain normal retries and safe abstention at resource bounds
    expanded = {item.chunk_id: item for item in results}
    for row, filename in rows:
        table = decode_table_chunk(row.text)
        if (
            not table
            or table.status != "certain"
            or row.user_id != user_id
            or row.document_id not in allowed_document_ids
            or table.document_id != row.document_id
            or table.page_number not in row.page_numbers
        ):
            continue
        seed = (row.document_id, table.table_id)
        continuation = (row.document_id, table.continuation_of)
        if seed not in seeds and continuation not in seeds:
            continue
        expanded.setdefault(
            row.id,
            VectorSearchResult(
                row.id,
                user_id,
                row.document_id,
                filename,
                row.page_numbers,
                row.text,
                seeds.get(seed, seeds.get(continuation, 0)),
            ),
        )
    return list(expanded.values())
