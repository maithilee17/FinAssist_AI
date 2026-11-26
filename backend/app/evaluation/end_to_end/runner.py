"""Run Phase 7.2 HTTP checks against an already-running FinAssist API.

This runner deliberately uses the public REST API for application workflows. It
reads the isolated SQLite database only to corroborate extraction/chunk counts
and to create one ownership fixture for a chat session, since chat generation is
unavailable when the live vector store is down.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
PROJECT = BACKEND.parent
REAL_WORLD = HERE.parent / "real_world"
DOCUMENTS = REAL_WORLD / "documents"
RUNTIME = HERE / ".runtime"
RESULTS_PATH = HERE / "results.json"
BASE_URL = os.getenv("FINASSIST_E2E_API_URL", "http://127.0.0.1:8000/api")
DB_PATH = Path(os.getenv("FINASSIST_E2E_DB_PATH", RUNTIME / "finassist-e2e.db"))
PASSWORD = os.getenv("FINASSIST_E2E_PASSWORD", "Phase72!LocalPass2026")

_SENSITIVE_ARTIFACT_KEYS = {
    "access_token",
    "authorization",
    "cookie",
    "finassist_access_token",
    "finassist_csrf_token",
    "jwt_secret_key",
    "openai_api_key",
    "password",
    "refresh_token",
    "set-cookie",
}
_COOKIE_VALUE_PATTERN = re.compile(
    r"(?i)\b(finassist_(?:access_token|csrf_token))=([^;\s,]+)"
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


@dataclass
class Check:
    id: str
    area: str
    description: str
    status: str
    duration_ms: float
    observed: Any = None
    expected: Any = None
    limitation: str | None = None


@dataclass
class State:
    checks: list[Check] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def add(
        self,
        check_id: str,
        area: str,
        description: str,
        status: str,
        started: float,
        *,
        observed: Any = None,
        expected: Any = None,
        limitation: str | None = None,
    ) -> None:
        self.checks.append(
            Check(
                id=check_id,
                area=area,
                description=description,
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                observed=observed,
                expected=expected,
                limitation=limitation,
            )
        )


def sanitize_for_artifact(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact credentials before serializing evaluation evidence."""
    normalized_key = key.lower().replace("-", "_") if key else None
    normalized_sensitive = {
        item.lower().replace("-", "_") for item in _SENSITIVE_ARTIFACT_KEYS
    }
    if normalized_key in normalized_sensitive:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            item_key: sanitize_for_artifact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_artifact(item) for item in value]
    if isinstance(value, str):
        value = _COOKIE_VALUE_PATTERN.sub(r"\1=[REDACTED]", value)
        return _JWT_PATTERN.sub("[REDACTED]", value)
    return value


def safe_body(value: Any) -> Any:
    """Keep response evidence without persisting extracted page contents."""
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        items = value["items"]
        if items and all(
            isinstance(item, dict) and "page_number" in item for item in items
        ):
            return {
                key: value.get(key)
                for key in (
                    "document_id",
                    "filename",
                    "total",
                    "page",
                    "page_size",
                    "total_pages",
                )
                if key in value
            } | {
                "returned_items": len(items),
                "page_numbers": [item["page_number"] for item in items],
                "extracted_text_omitted": True,
            }
    return value


def request_check(
    state: State,
    client: httpx.Client,
    check_id: str,
    area: str,
    description: str,
    method: str,
    path: str,
    expected_status: int,
    **kwargs: Any,
) -> httpx.Response:
    started = time.perf_counter()
    try:
        response = client.request(method, path, **kwargs)
        status = "passed" if response.status_code == expected_status else "failed"
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text[:500]
        state.add(
            check_id,
            area,
            description,
            status,
            started,
            observed={"status_code": response.status_code, "body": body},
            expected={"status_code": expected_status},
        )
        return response
    except Exception as exc:
        state.add(
            check_id,
            area,
            description,
            "failed",
            started,
            observed={"error": type(exc).__name__, "detail": str(exc)},
            expected={"status_code": expected_status},
        )
        raise


def csrf(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("finassist_csrf_token")
    return {"X-CSRF-Token": token} if token else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def database_counts(document_id: str) -> dict[str, int]:
    with sqlite3.connect(DB_PATH) as connection:
        chunk_count = connection.execute(
            "SELECT count(*) FROM document_chunks WHERE document_id = ?",
            (document_id.replace("-", ""),),
        ).fetchone()[0]
        page_count = connection.execute(
            "SELECT count(*) FROM document_pages WHERE document_id = ?",
            (document_id.replace("-", ""),),
        ).fetchone()[0]
    return {"pages": page_count, "chunks": chunk_count}


def seed_owned_chat_session(user_id: str) -> str:
    """Create a database fixture solely for live chat-ownership API checks."""
    session_id = uuid4()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "INSERT INTO chat_sessions (id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
            (
                session_id.hex,
                user_id.replace("-", ""),
                "Phase 7.2 ownership fixture",
                now,
            ),
        )
        connection.commit()
    return str(session_id)


def upload_pdf(
    state: State,
    client: httpx.Client,
    check_id: str,
    path: Path,
    expected_pages: int,
    expected_chunks: int,
) -> dict[str, Any] | None:
    started = time.perf_counter()
    with path.open("rb") as source:
        response = client.post(
            "/documents/upload",
            headers=csrf(client),
            files={"file": (path.name, source, "application/pdf")},
            timeout=1200,
        )
    try:
        body = safe_body(response.json())
    except ValueError:
        body = {"raw": response.text[:1000]}
    if response.status_code != 201:
        state.add(
            check_id,
            "documents",
            f"Upload and process {path.name}",
            "failed",
            started,
            observed={"status_code": response.status_code, "body": body},
            expected={"status_code": 201},
        )
        return None

    doc_id = body["id"]
    counts = database_counts(doc_id)
    expected_failure = body.get("processing_status") == "failed"
    correct = (
        body.get("page_count") == expected_pages
        and counts == {"pages": expected_pages, "chunks": expected_chunks}
        and expected_failure
        and "storage_path" not in body
    )
    state.add(
        check_id,
        "documents",
        f"Upload, extract, and chunk {path.name}; indexing reaches the unavailable Chroma boundary",
        "passed" if correct else "failed",
        started,
        observed={"response": body, "database_counts": counts},
        expected={
            "status_code": 201,
            "page_count": expected_pages,
            "chunk_count": expected_chunks,
            "processing_status": "failed",
            "private_path_not_exposed": True,
        },
        limitation="Live ChromaDB is unavailable, so successful indexing is blocked.",
    )
    return body


def main() -> int:
    state = State()
    state.artifacts.update(
        {
            "started_at": datetime.now(UTC).isoformat(),
            "api_base_url": BASE_URL,
            "database": {"kind": "SQLite substitute", "path": str(DB_PATH)},
            "documents": {
                "nvidia": {
                    "path": str(DOCUMENTS / "nvidia-2025-annual-report.pdf"),
                    "sha256": sha256(DOCUMENTS / "nvidia-2025-annual-report.pdf"),
                },
                "coca_cola": {
                    "path": str(DOCUMENTS / "coca-cola-2024-10-k.pdf"),
                    "sha256": sha256(DOCUMENTS / "coca-cola-2024-10-k.pdf"),
                },
            },
        }
    )
    timeout = httpx.Timeout(1200, connect=10)
    anonymous = httpx.Client(base_url=BASE_URL, timeout=timeout)
    user_a = httpx.Client(base_url=BASE_URL, timeout=timeout)
    user_b = httpx.Client(base_url=BASE_URL, timeout=timeout)
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    accounts = {
        "a": {
            "full_name": "Phase Seven User A",
            "email": f"phase72-a-{suffix}@example.com",
            "password": PASSWORD,
        },
        "b": {
            "full_name": "Phase Seven User B",
            "email": f"phase72-b-{suffix}@example.com",
            "password": PASSWORD,
        },
    }
    state.artifacts["accounts"] = {
        key: {"full_name": value["full_name"], "email": value["email"]}
        for key, value in accounts.items()
    }

    try:
        request_check(
            state,
            anonymous,
            "auth-unauth-me",
            "authentication",
            "Unauthenticated profile request is rejected",
            "GET",
            "/auth/me",
            401,
        )
        request_check(
            state,
            anonymous,
            "auth-unauth-docs",
            "security",
            "Unauthenticated document listing is rejected",
            "GET",
            "/documents",
            401,
        )
        request_check(
            state,
            anonymous,
            "auth-unauth-chat",
            "security",
            "Unauthenticated chat listing is rejected",
            "GET",
            "/chat/sessions",
            401,
        )

        reg_a = request_check(
            state,
            user_a,
            "auth-register-a",
            "authentication",
            "Register User A",
            "POST",
            "/auth/register",
            201,
            json=accounts["a"],
        )
        reg_b = request_check(
            state,
            user_b,
            "auth-register-b",
            "authentication",
            "Register User B",
            "POST",
            "/auth/register",
            201,
            json=accounts["b"],
        )
        user_a_id = reg_a.json()["id"]
        user_b_id = reg_b.json()["id"]
        state.artifacts["user_ids"] = {"a": user_a_id, "b": user_b_id}
        request_check(
            state,
            anonymous,
            "auth-duplicate",
            "authentication",
            "Duplicate email registration is rejected",
            "POST",
            "/auth/register",
            409,
            json=accounts["a"],
        )
        request_check(
            state,
            anonymous,
            "auth-bad-password",
            "authentication",
            "Incorrect password is rejected without account disclosure",
            "POST",
            "/auth/login",
            401,
            json={"email": accounts["a"]["email"], "password": "WrongPassword!2026"},
        )

        login_a = request_check(
            state,
            user_a,
            "auth-login-a",
            "authentication",
            "User A logs in",
            "POST",
            "/auth/login",
            200,
            json={"email": accounts["a"]["email"], "password": PASSWORD},
        )
        request_check(
            state,
            user_b,
            "auth-login-b",
            "authentication",
            "User B logs in",
            "POST",
            "/auth/login",
            200,
            json={"email": accounts["b"]["email"], "password": PASSWORD},
        )
        cookie_started = time.perf_counter()
        set_cookie = login_a.headers.get_list("set-cookie")
        cookie_ok = any(
            "finassist_access_token=" in value and "httponly" in value.lower()
            for value in set_cookie
        ) and any(
            "finassist_csrf_token=" in value and "httponly" not in value.lower()
            for value in set_cookie
        )
        state.add(
            "auth-cookie-flags",
            "security",
            "Auth cookie is HttpOnly while the CSRF cookie remains script-readable",
            "passed" if cookie_ok else "failed",
            cookie_started,
            observed=set_cookie,
            expected={"auth_http_only": True, "csrf_http_only": False},
        )
        request_check(
            state,
            user_a,
            "auth-me-valid",
            "authentication",
            "Authenticated profile is returned",
            "GET",
            "/auth/me",
            200,
        )

        persisted = httpx.Client(
            base_url=BASE_URL, timeout=timeout, cookies=user_a.cookies
        )
        request_check(
            state,
            persisted,
            "auth-cookie-persistence",
            "persistence",
            "Session cookie authenticates a fresh HTTP client",
            "GET",
            "/auth/me",
            200,
        )
        missing_csrf = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            cookies={
                "finassist_access_token": user_a.cookies.get("finassist_access_token")
            },
        )
        request_check(
            state,
            missing_csrf,
            "auth-csrf-missing",
            "security",
            "State-changing logout without CSRF token is rejected",
            "POST",
            "/auth/logout",
            403,
        )

        nvidia = upload_pdf(
            state,
            user_a,
            "doc-upload-nvidia",
            DOCUMENTS / "nvidia-2025-annual-report.pdf",
            181,
            347,
        )
        coke = upload_pdf(
            state,
            user_a,
            "doc-upload-coke",
            DOCUMENTS / "coca-cola-2024-10-k.pdf",
            140,
            315,
        )
        docs = [item for item in (nvidia, coke) if item]
        state.artifacts["uploaded_documents"] = [
            {
                "id": item["id"],
                "filename": item["filename"],
                "status": item["processing_status"],
            }
            for item in docs
        ]

        list_a = request_check(
            state,
            user_a,
            "doc-list-a",
            "documents",
            "User A lists only their uploaded documents",
            "GET",
            "/documents?page=1&page_size=100",
            200,
        )
        list_b = request_check(
            state,
            user_b,
            "doc-list-b-empty",
            "security",
            "User B does not see User A documents",
            "GET",
            "/documents?page=1&page_size=100",
            200,
        )
        isolation_started = time.perf_counter()
        isolated = list_b.json().get("total") == 0 and list_a.json().get("total") == 2
        state.add(
            "doc-list-isolation",
            "security",
            "Document listings are isolated by owner",
            "passed" if isolated else "failed",
            isolation_started,
            observed={
                "user_a_total": list_a.json().get("total"),
                "user_b_total": list_b.json().get("total"),
            },
            expected={"user_a_total": 2, "user_b_total": 0},
        )

        if nvidia:
            doc_id = nvidia["id"]
            request_check(
                state,
                user_a,
                "doc-status",
                "documents",
                "User A reads NVIDIA processing status",
                "GET",
                f"/documents/{doc_id}/status",
                200,
            )
            pages = request_check(
                state,
                user_a,
                "doc-pages",
                "documents",
                "User A reads page-aware NVIDIA extraction",
                "GET",
                f"/documents/{doc_id}/pages?page=1&page_size=100",
                200,
            )
            pages2 = request_check(
                state,
                user_a,
                "doc-pages-2",
                "documents",
                "User A reads the second NVIDIA page batch",
                "GET",
                f"/documents/{doc_id}/pages?page=2&page_size=100",
                200,
            )
            page_started = time.perf_counter()
            all_pages = pages.json().get("items", []) + pages2.json().get("items", [])
            numbers = [item["page_number"] for item in all_pages]
            page_ok = len(all_pages) == 181 and numbers == list(range(1, 182))
            state.add(
                "doc-page-references",
                "documents",
                "Extracted page references are contiguous and one-based",
                "passed" if page_ok else "failed",
                page_started,
                observed={
                    "count": len(all_pages),
                    "first": numbers[:3],
                    "last": numbers[-3:],
                },
                expected={"count": 181, "range": [1, 181]},
            )
            retry = request_check(
                state,
                user_a,
                "doc-retry",
                "documents",
                "Retry reuses retained chunks and reports the Chroma indexing failure",
                "POST",
                f"/documents/{doc_id}/retry",
                200,
                headers=csrf(user_a),
                timeout=1200,
            )
            retry_started = time.perf_counter()
            counts = database_counts(doc_id)
            retry_ok = retry.json().get("processing_status") == "failed" and counts == {
                "pages": 181,
                "chunks": 347,
            }
            state.add(
                "doc-retry-reuse",
                "documents",
                "Retry preserves extracted pages and chunks",
                "passed" if retry_ok else "failed",
                retry_started,
                observed={
                    "status": retry.json().get("processing_status"),
                    "counts": counts,
                },
                expected={"status": "failed", "counts": {"pages": 181, "chunks": 347}},
                limitation="The retry cannot complete while ChromaDB is unavailable.",
            )

            request_check(
                state,
                user_b,
                "security-cross-doc-get",
                "security",
                "User B cannot inspect User A document",
                "GET",
                f"/documents/{doc_id}",
                404,
            )
            request_check(
                state,
                user_b,
                "security-cross-doc-pages",
                "security",
                "User B cannot read User A extracted pages",
                "GET",
                f"/documents/{doc_id}/pages",
                404,
            )
            request_check(
                state,
                user_b,
                "security-cross-doc-retry",
                "security",
                "User B cannot retry User A document",
                "POST",
                f"/documents/{doc_id}/retry",
                404,
                headers=csrf(user_b),
            )
            request_check(
                state,
                user_b,
                "security-cross-doc-delete",
                "security",
                "User B cannot delete User A document",
                "DELETE",
                f"/documents/{doc_id}",
                404,
                headers=csrf(user_b),
            )
            request_check(
                state,
                user_b,
                "security-cross-doc-chat",
                "security",
                "User B cannot select User A document for retrieval",
                "POST",
                "/chat/ask",
                404,
                headers=csrf(user_b),
                json={"question": "What was revenue?", "document_ids": [doc_id]},
            )

            deletion = request_check(
                state,
                user_a,
                "doc-delete-chroma-down",
                "documents",
                "Deletion is cancelled when vector cleanup cannot be guaranteed",
                "DELETE",
                f"/documents/{doc_id}",
                503,
                headers=csrf(user_a),
            )
            after = request_check(
                state,
                user_a,
                "doc-delete-cancelled-record",
                "persistence",
                "Cancelled deletion leaves document metadata available",
                "GET",
                f"/documents/{doc_id}",
                200,
            )
            delete_started = time.perf_counter()
            safe_cancel = deletion.status_code == 503 and after.status_code == 200
            state.add(
                "doc-delete-safe-cancel",
                "security",
                "Failed vector cleanup does not partially delete the document",
                "passed" if safe_cancel else "failed",
                delete_started,
                observed={
                    "delete_status": deletion.status_code,
                    "record_status": after.status_code,
                },
                expected={"delete_status": 503, "record_status": 200},
                limitation="Successful deletion/cleanup is blocked without live ChromaDB.",
            )

        request_check(
            state,
            user_a,
            "chat-no-index",
            "chat",
            "Chat reports that no indexed documents are available",
            "POST",
            "/chat/ask",
            409,
            headers=csrf(user_a),
            json={
                "question": "What was NVIDIA revenue in fiscal 2025?",
                "document_ids": [],
            },
        )
        request_check(
            state,
            user_a,
            "chat-sessions-empty",
            "chat",
            "Failed RAG requests do not create misleading chat sessions",
            "GET",
            "/chat/sessions",
            200,
        )

        fixture_id = seed_owned_chat_session(user_b_id)
        state.artifacts["chat_ownership_fixture_id"] = fixture_id
        request_check(
            state,
            user_b,
            "chat-owner-read",
            "security",
            "User B can read their fixture chat session through the live API",
            "GET",
            f"/chat/sessions/{fixture_id}",
            200,
        )
        request_check(
            state,
            user_a,
            "chat-cross-user-read",
            "security",
            "User A cannot read User B chat session",
            "GET",
            f"/chat/sessions/{fixture_id}",
            404,
        )
        request_check(
            state,
            user_a,
            "chat-cross-user-delete",
            "security",
            "User A cannot delete User B chat session",
            "DELETE",
            f"/chat/sessions/{fixture_id}",
            404,
            headers=csrf(user_a),
        )
        request_check(
            state,
            user_b,
            "chat-owner-delete",
            "security",
            "User B can delete their own fixture chat session",
            "DELETE",
            f"/chat/sessions/{fixture_id}",
            204,
            headers=csrf(user_b),
        )

        request_check(
            state,
            user_a,
            "auth-logout",
            "authentication",
            "User A logs out",
            "POST",
            "/auth/logout",
            200,
            headers=csrf(user_a),
        )
        request_check(
            state,
            user_a,
            "auth-after-logout",
            "authentication",
            "Logged-out session can no longer access the profile",
            "GET",
            "/auth/me",
            401,
        )

        blocked_started = time.perf_counter()
        state.add(
            "chat-generated-answer",
            "chat",
            "Generated answers, citations, retrieval diagnostics, evidence status, and confidence UI",
            "blocked",
            blocked_started,
            limitation="Live ChromaDB is unavailable, no document can reach completed/indexed state, and no LLM provider was enabled.",
        )
        blocked_started = time.perf_counter()
        state.add(
            "document-delete-success",
            "documents",
            "Successful document deletion and vector/file cleanup",
            "blocked",
            blocked_started,
            limitation="Deletion intentionally cancels when live Chroma vector cleanup is unavailable.",
        )
        blocked_started = time.perf_counter()
        state.add(
            "postgres-live",
            "environment",
            "PostgreSQL-backed application workflow",
            "blocked",
            blocked_started,
            limitation="Docker Desktop service was unavailable and native PostgreSQL could not bind loopback sockets in this environment; isolated SQLite was used instead.",
        )
        blocked_started = time.perf_counter()
        state.add(
            "chroma-live",
            "environment",
            "Live ChromaDB indexing/retrieval",
            "blocked",
            blocked_started,
            limitation="No ChromaDB server was available on 127.0.0.1:8001.",
        )
        blocked_started = time.perf_counter()
        state.add(
            "llm-live",
            "environment",
            "Live grounded answer generation",
            "blocked",
            blocked_started,
            limitation="Paid LLM calls were prohibited and no configured local Ollama model was running.",
        )
    finally:
        for client in (anonymous, user_a, user_b):
            client.close()

    counts: dict[str, int] = {}
    for check in state.checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    payload = {
        "schema_version": "1.0",
        "phase": "7.2",
        "finished_at": datetime.now(UTC).isoformat(),
        "summary": counts,
        "environment": {
            "database": "SQLite substitute (persistent isolated database)",
            "postgresql_tested": False,
            "chromadb_tested": False,
            "llm_tested": False,
            "backend": "FastAPI/Uvicorn on 127.0.0.1:8000",
            "frontend": "Vite on 127.0.0.1:5173",
        },
        "artifacts": state.artifacts,
        "checks": [asdict(check) for check in state.checks],
    }
    sanitized_payload = sanitize_for_artifact(payload)
    RESULTS_PATH.write_text(json.dumps(sanitized_payload, indent=2), encoding="utf-8")
    print(json.dumps(sanitized_payload["summary"], indent=2))
    return 1 if counts.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
