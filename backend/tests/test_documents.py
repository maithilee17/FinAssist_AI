"""Document upload, ownership, pagination, processing, and deletion API tests."""

from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models.document import Document, DocumentChunk, DocumentPage, DocumentStatus
from app.services.embedding_service import EmbeddingServiceError
from app.services.rag_dependencies import get_embedding_service
from app.services.storage_service import PrivateDocumentStorage

pytestmark = pytest.mark.anyio


async def create_user_token(client: httpx.AsyncClient, email: str) -> str:
    password = "SecureDocuments123!"
    response = await client.post(
        "/api/auth/register",
        json={"full_name": "Document Tester", "email": email, "password": password},
    )
    assert response.status_code == 201
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


async def upload_pdf(
    client: httpx.AsyncClient,
    token: str,
    content: bytes,
    filename: str = "annual-report.pdf",
) -> httpx.Response:
    return await client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content, "application/pdf")},
        timeout=30,
    )


async def test_valid_pdf_upload_processes_pages_and_chunks(
    client: httpx.AsyncClient,
    pdf_bytes_factory,
    session_factory: async_sessionmaker[AsyncSession],
    private_storage: PrivateDocumentStorage,
) -> None:
    token = await create_user_token(client, "upload@example.com")
    pdf = pdf_bytes_factory(
        ["FY2025 Revenue $1,250.50 and margin -3.2%", "Second page evidence"]
    )
    response = await upload_pdf(client, token, pdf)

    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "completed"
    assert body["page_count"] == 2
    assert body["indexed_chunk_count"] >= 1
    assert body["embedding_model"] == "test-financial-embedding"
    assert "storage_path" not in body

    document_id = UUID(body["id"])
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        page_count = await session.scalar(
            select(func.count(DocumentPage.id)).where(
                DocumentPage.document_id == document_id
            )
        )
        chunk_count = await session.scalar(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == document_id
            )
        )
    assert document is not None
    assert private_storage.resolve(document.storage_path).is_file()
    assert page_count == 2
    assert chunk_count and chunk_count >= 1


@pytest.mark.parametrize(
    ("filename", "content", "mime_type", "expected_status"),
    [
        ("notes.txt", b"plain text", "text/plain", 415),
        ("fake.pdf", b"not a real pdf", "application/pdf", 422),
        ("fake.pdf", b"%PDF-corrupted", "application/pdf", 422),
    ],
)
async def test_non_pdf_and_invalid_pdf_rejection(
    client: httpx.AsyncClient,
    filename: str,
    content: bytes,
    mime_type: str,
    expected_status: int,
) -> None:
    token = await create_user_token(client, f"{filename.replace('.', '-')}@example.com")
    response = await client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content, mime_type)},
    )
    assert response.status_code == expected_status


async def test_oversized_file_is_rejected_and_cleaned(
    client: httpx.AsyncClient,
    private_storage: PrivateDocumentStorage,
) -> None:
    token = await create_user_token(client, "oversized@example.com")
    private_storage.max_size_bytes = 32
    response = await upload_pdf(client, token, b"%PDF-1.7\n" + b"x" * 100)

    assert response.status_code == 413
    assert not list(private_storage.root.rglob("*.pdf"))
    assert not list(private_storage.root.rglob("*.part"))


async def test_unauthenticated_upload_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/documents/upload",
        files={"file": ("report.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert response.status_code == 401


async def test_private_storage_rejects_path_traversal(
    private_storage: PrivateDocumentStorage,
) -> None:
    with pytest.raises(ValueError, match="escapes"):
        private_storage.resolve("../outside.pdf")


async def test_listing_pages_and_ownership_are_isolated(
    client: httpx.AsyncClient, pdf_bytes_factory
) -> None:
    owner_token = await create_user_token(client, "owner@example.com")
    other_token = await create_user_token(client, "other@example.com")
    uploaded = await upload_pdf(
        client, owner_token, pdf_bytes_factory(["Owner-only revenue data"])
    )
    document_id = uploaded.json()["id"]

    owner_list = await client.get(
        "/api/documents", headers={"Authorization": f"Bearer {owner_token}"}
    )
    owner_detail = await client.get(
        f"/api/documents/{document_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    owner_pages = await client.get(
        f"/api/documents/{document_id}/pages",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    owner_status = await client.get(
        f"/api/documents/{document_id}/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    other_detail = await client.get(
        f"/api/documents/{document_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    other_delete = await client.delete(
        f"/api/documents/{document_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert owner_list.status_code == 200
    assert owner_list.json()["total"] == 1
    assert owner_detail.status_code == 200
    assert owner_pages.status_code == 200
    assert owner_pages.json()["items"][0]["page_number"] == 1
    assert owner_status.json()["processing_status"] == "completed"
    assert other_detail.status_code == 404
    assert other_delete.status_code == 404


async def test_failed_document_can_be_retried(
    client: httpx.AsyncClient,
    pdf_bytes_factory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = await create_user_token(client, "retry@example.com")
    uploaded = (
        await upload_pdf(client, token, pdf_bytes_factory(["Retry source text"]))
    ).json()
    document_id = UUID(uploaded["id"])
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        document.processing_status = DocumentStatus.FAILED
        document.processing_error = "Simulated recoverable failure"
        await session.commit()

    response = await client.post(
        f"/api/documents/{document_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "completed"
    assert response.json()["processing_error"] is None


async def test_indexing_failure_retains_chunks_and_retry_does_not_require_reupload(
    client: httpx.AsyncClient,
    pdf_bytes_factory,
    session_factory: async_sessionmaker[AsyncSession],
    fake_embedding_service,
) -> None:
    class FailingEmbedding:
        model_name = "temporarily-unavailable-model"

        @staticmethod
        def embed_documents(texts):
            del texts
            raise EmbeddingServiceError(
                "Embedding model is temporarily unavailable",
                code="model_load_failed",
            )

    app.dependency_overrides[get_embedding_service] = lambda: FailingEmbedding()
    token = await create_user_token(client, "index-retry@example.com")
    response = await upload_pdf(
        client, token, pdf_bytes_factory(["FY2025 revenue was $1,250.50"])
    )
    assert response.status_code == 201
    assert response.json()["processing_status"] == "failed"
    assert "model_load_failed" in response.json()["processing_error"]
    document_id = UUID(response.json()["id"])
    async with session_factory() as session:
        chunk_count = await session.scalar(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == document_id
            )
        )
    assert chunk_count and chunk_count >= 1

    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service
    retried = await client.post(
        f"/api/documents/{document_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retried.status_code == 200
    assert retried.json()["processing_status"] == "completed"
    assert retried.json()["indexed_chunk_count"] == chunk_count


async def test_delete_removes_database_artifacts_and_original_file(
    client: httpx.AsyncClient,
    pdf_bytes_factory,
    session_factory: async_sessionmaker[AsyncSession],
    private_storage: PrivateDocumentStorage,
    fake_vector_store,
) -> None:
    token = await create_user_token(client, "delete@example.com")
    uploaded = (
        await upload_pdf(client, token, pdf_bytes_factory(["Delete this report"]))
    ).json()
    document_id = UUID(uploaded["id"])
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        stored_file = private_storage.resolve(document.storage_path)
    assert stored_file.exists()
    assert any(
        chunk.document_id == document_id
        for chunk, _ in fake_vector_store.records.values()
    )

    response = await client.delete(
        f"/api/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 204
    assert not stored_file.exists()
    assert not any(
        chunk.document_id == document_id
        for chunk, _ in fake_vector_store.records.values()
    )
    async with session_factory() as session:
        assert await session.get(Document, document_id) is None
        assert (
            await session.scalar(
                select(func.count(DocumentPage.id)).where(
                    DocumentPage.document_id == document_id
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.document_id == document_id
                )
            )
            == 0
        )


async def test_delete_cleanup_failure_is_quarantined_without_restoring_database_record(
    client: httpx.AsyncClient,
    pdf_bytes_factory,
    session_factory: async_sessionmaker[AsyncSession],
    private_storage: PrivateDocumentStorage,
    monkeypatch,
) -> None:
    token = await create_user_token(client, "partial-delete@example.com")
    uploaded = (
        await upload_pdf(client, token, pdf_bytes_factory(["Quarantine cleanup test"]))
    ).json()
    document_id = UUID(uploaded["id"])
    monkeypatch.setattr(private_storage, "finalize_delete", lambda ticket: False)

    response = await client.delete(
        f"/api/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 204
    async with session_factory() as session:
        assert await session.get(Document, document_id) is None
    assert list(private_storage.trash_dir.glob("*.deleting"))
