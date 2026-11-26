"""Phase 3E Lite security and tenant isolation verification tests."""

from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def register_user(client: AsyncClient, email: str) -> str:
    pwd = "SecurePhase3ePassword123!"
    reg = await client.post(
        "/api/auth/register",
        json={"full_name": "Security User", "email": email, "password": pwd},
    )
    assert reg.status_code == 201
    login = await client.post("/api/auth/login", json={"email": email, "password": pwd})
    assert login.status_code == 200
    return login.json()["access_token"]


async def test_unauthenticated_requests_strictly_rejected(client: AsyncClient):
    """Verify protected endpoints return 401 without authentication."""
    random_id = uuid4()
    r1 = await client.get("/api/documents")
    assert r1.status_code == 401

    r2 = await client.get(f"/api/documents/{random_id}")
    assert r2.status_code == 401

    r3 = await client.get(f"/api/dashboard/{random_id}")
    assert r3.status_code == 401

    r4 = await client.post("/api/chat/ask", json={"question": "What is revenue?"})
    assert r4.status_code == 401


async def test_invalid_or_forged_jwt_token_rejected(client: AsyncClient):
    """Verify tampering with JWT signature results in 401."""
    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkZvcmdlZCJ9.fake_signature_abc123"
    headers = {"Authorization": f"Bearer {fake_token}"}

    r = await client.get("/api/documents", headers=headers)
    assert r.status_code == 401


async def test_upload_rejects_non_pdf_file_extensions(client: AsyncClient):
    """Verify non-PDF uploads are rejected immediately."""
    token = await register_user(client, f"sec-upload-{uuid4().hex[:6]}@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    files = {"file": ("malicious.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/x-dosexec")}
    r = await client.post("/api/documents/upload", headers=headers, files=files)
    assert r.status_code in (400, 415)
    assert "pdf" in r.text.lower() or "unsupported" in r.text.lower()


async def test_cross_tenant_document_and_dashboard_isolation(client: AsyncClient):
    """Verify User B cannot access User A's document or dashboard under any circumstances."""
    user_a_token = await register_user(client, f"user-a-{uuid4().hex[:6]}@example.com")
    user_b_token = await register_user(client, f"user-b-{uuid4().hex[:6]}@example.com")

    # User A uploads a minimal valid PDF
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 300 144]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n"
        b"0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n"
    )
    up_resp = await client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {user_a_token}"},
        files={"file": ("tenant_a_report.pdf", minimal_pdf, "application/pdf")},
    )
    assert up_resp.status_code in (200, 201)
    doc_id = up_resp.json()["id"]

    # User B attempts to access User A's document metadata -> 404
    r_meta = await client.get(
        f"/api/documents/{doc_id}",
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert r_meta.status_code == 404

    # User B attempts to access User A's dashboard -> 404
    r_dash = await client.get(
        f"/api/dashboard/{doc_id}",
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert r_dash.status_code == 404

    # User B attempts to access User A's pages -> 404
    r_pages = await client.get(
        f"/api/documents/{doc_id}/pages",
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert r_pages.status_code == 404

    # User B attempts to delete User A's document -> 404
    r_del = await client.delete(
        f"/api/documents/{doc_id}",
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert r_del.status_code == 404
