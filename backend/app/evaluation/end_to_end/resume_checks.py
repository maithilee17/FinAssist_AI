"""Run only the inexpensive Phase 7.2 checks left after an interrupted run.

This script intentionally does not upload or reprocess PDFs. It uses the two
accounts and document IDs recorded by the completed runner and corroborates
the browser-uploaded User B document from the persisted database.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.evaluation.end_to_end.runner import sanitize_for_artifact

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results.json"
OUTPUT = HERE / "resume_results.json"
DB_PATH = HERE / ".runtime" / "finassist-e2e.db"
UPLOAD_ROOT = HERE / ".runtime" / "uploads"
BASE_URL = os.getenv("FINASSIST_E2E_API_URL", "http://127.0.0.1:8000/api")
PASSWORD = os.getenv("FINASSIST_E2E_PASSWORD", "Phase72!LocalPass2026")


def body(response: httpx.Response) -> Any:
    try:
        value = response.json()
    except ValueError:
        return response.text[:1000]
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


def main() -> int:
    prior = json.loads(RESULTS.read_text(encoding="utf-8"))
    accounts = prior["artifacts"]["accounts"]
    checks: list[dict[str, Any]] = []

    def check(
        check_id: str,
        area: str,
        description: str,
        response: httpx.Response,
        expected: int,
        started: float,
        *,
        detail: Any = None,
        limitation: str | None = None,
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "area": area,
                "description": description,
                "status": "passed" if response.status_code == expected else "failed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "observed": {
                    "status_code": response.status_code,
                    "body": body(response),
                    "detail": detail,
                },
                "expected": {"status_code": expected},
                "limitation": limitation,
            }
        )

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, user_id, filename, storage_path, file_size, page_count,
                   processing_status, processing_error, indexed_chunk_count,
                   indexed_at
            FROM documents ORDER BY upload_date
            """
        ).fetchall()
        documents: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["id"] = item["id"]
            item["page_rows"] = connection.execute(
                "SELECT count(*) FROM document_pages WHERE document_id = ?",
                (item["id"],),
            ).fetchone()[0]
            item["chunk_rows"] = connection.execute(
                "SELECT count(*) FROM document_chunks WHERE document_id = ?",
                (item["id"],),
            ).fetchone()[0]
            stored = UPLOAD_ROOT / item["storage_path"]
            item["file_exists"] = stored.is_file()
            item["stored_size"] = stored.stat().st_size if stored.exists() else None
            documents.append(item)
        migration = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        users = [dict(row) for row in connection.execute("SELECT id, email FROM users")]

    user_ids = {row["email"]: row["id"] for row in users}
    user_b_id = user_ids[accounts["b"]["email"]]
    user_b_docs = [item for item in documents if item["user_id"] == user_b_id]
    if len(user_b_docs) != 1:
        raise RuntimeError(
            f"Expected one browser-uploaded User B document, found {len(user_b_docs)}"
        )
    user_b_doc = user_b_docs[0]

    clients = {
        name: httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(30, connect=5))
        for name in ("a", "b")
    }
    try:
        for name, client in clients.items():
            started = time.perf_counter()
            response = client.post(
                "/auth/login",
                json={"email": accounts[name]["email"], "password": PASSWORD},
            )
            check(
                f"resume-login-{name}",
                "authentication",
                f"Existing User {name.upper()} logs in after service resume",
                response,
                200,
                started,
            )

        def csrf(client: httpx.Client) -> dict[str, str]:
            token = client.cookies.get("finassist_csrf_token")
            return {"X-CSRF-Token": token} if token else {}

        started = time.perf_counter()
        response = clients["b"].get(f"/documents/{user_b_doc['id']}")
        check(
            "resume-browser-upload-record",
            "documents",
            "Browser-uploaded Coca-Cola document is available to User B",
            response,
            200,
            started,
            detail={
                "page_rows": user_b_doc["page_rows"],
                "chunk_rows": user_b_doc["chunk_rows"],
                "file_exists": user_b_doc["file_exists"],
                "stored_size": user_b_doc["stored_size"],
            },
            limitation="Indexing failed because live ChromaDB was unavailable.",
        )
        started = time.perf_counter()
        response = clients["b"].get(
            f"/documents/{user_b_doc['id']}/pages?page=1&page_size=100"
        )
        first_pages = response.json()
        second_response = clients["b"].get(
            f"/documents/{user_b_doc['id']}/pages?page=2&page_size=100"
        )
        second_pages = second_response.json()
        page_numbers = (
            [
                item["page_number"]
                for item in first_pages.get("items", []) + second_pages.get("items", [])
            ]
            if isinstance(first_pages, dict) and isinstance(second_pages, dict)
            else []
        )
        expected_status = (
            200
            if second_response.status_code == 200
            and page_numbers == list(range(1, 141))
            else -1
        )
        check(
            "resume-browser-upload-pages",
            "documents",
            "Browser-uploaded Coca-Cola pages remain one-based and contiguous",
            response,
            expected_status,
            started,
            detail={
                "second_status": second_response.status_code,
                "page_count": len(page_numbers),
            },
        )

        cross_requests = (
            (
                "get",
                f"/documents/{user_b_doc['id']}",
                None,
                "User A cannot inspect User B document",
            ),
            (
                "get",
                f"/documents/{user_b_doc['id']}/pages",
                None,
                "User A cannot inspect User B extracted pages/chunks",
            ),
            (
                "post",
                f"/documents/{user_b_doc['id']}/retry",
                None,
                "User A cannot retry User B document",
            ),
            (
                "delete",
                f"/documents/{user_b_doc['id']}",
                None,
                "User A cannot delete User B document",
            ),
            (
                "post",
                "/chat/ask",
                {
                    "question": "What was Coca-Cola net revenue in 2024?",
                    "document_ids": [user_b_doc["id"]],
                },
                "User A cannot retrieve User B document chunks",
            ),
        )
        for index, (method, path, payload, description) in enumerate(cross_requests, 1):
            started = time.perf_counter()
            response = clients["a"].request(
                method,
                path,
                headers=csrf(clients["a"]),
                json=payload,
            )
            check(
                f"resume-cross-user-{index}",
                "security",
                description,
                response,
                404,
                started,
            )

        questions = (
            ("exact", "What was NVIDIA revenue in fiscal 2025?"),
            ("conceptual", "What factors affected Coca-Cola operating margins?"),
            (
                "comparison",
                "Compare NVIDIA revenue between fiscal 2024 and fiscal 2025.",
            ),
            (
                "multi_passage",
                "Summarize NVIDIA data-center growth and the related supply risks.",
            ),
            ("missing", "What was NVIDIA's debt-to-equity ratio in fiscal 2027?"),
            (
                "multi_document",
                "Compare the main business risks disclosed by NVIDIA and Coca-Cola.",
            ),
        )
        for category, question in questions:
            started = time.perf_counter()
            response = clients["a"].post(
                "/chat/ask",
                headers=csrf(clients["a"]),
                json={"question": question, "document_ids": []},
            )
            check(
                f"resume-chat-{category}",
                "chat",
                f"{category.replace('_', ' ').title()} question fails safely with no indexed documents",
                response,
                409,
                started,
                limitation="No generated answer or citation was possible because ChromaDB indexing was unavailable.",
            )

        started = time.perf_counter()
        response = clients["b"].delete(
            f"/documents/{user_b_doc['id']}", headers=csrf(clients["b"])
        )
        check(
            "resume-own-delete-cancelled",
            "documents",
            "User B deletion safely cancels when vector cleanup is unavailable",
            response,
            503,
            started,
            limitation="PDF, relational rows, and chunks intentionally remain because vector cleanup could not be guaranteed.",
        )
        started = time.perf_counter()
        response = clients["b"].get(f"/documents/{user_b_doc['id']}")
        check(
            "resume-own-delete-record-retained",
            "persistence",
            "Cancelled deletion retains User B document record",
            response,
            200,
            started,
        )
    finally:
        for client in clients.values():
            client.close()

    summary: dict[str, int] = {}
    for item in checks:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
    output = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "migration_head": migration,
        "database": "persistent SQLite substitute",
        "documents": documents,
        "checks": checks,
    }
    OUTPUT.write_text(
        json.dumps(sanitize_for_artifact(output), indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 1 if summary.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
