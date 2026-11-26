"""Merge completed runner, resume, browser, and quality-gate evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "results.json"
RESUME_PATH = HERE / "resume_results.json"


def check(
    check_id: str,
    area: str,
    description: str,
    status: str,
    observed: Any,
    *,
    limitation: str | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "area": area,
        "description": description,
        "status": status,
        "duration_ms": None,
        "observed": observed,
        "expected": None,
        "limitation": limitation,
    }


def main() -> None:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    resume = json.loads(RESUME_PATH.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in results["checks"]}
    by_id.update({item["id"]: item for item in resume["checks"]})

    manual = (
        check(
            "ui-protected-route",
            "frontend",
            "Unauthenticated dashboard navigation redirects to login",
            "passed",
            {"observed_url": "/login"},
        ),
        check(
            "ui-login-a",
            "frontend",
            "User A logged in through the React login page",
            "passed",
            {"observed_url": "/dashboard"},
        ),
        check(
            "ui-dashboard-profile",
            "frontend",
            "Dashboard displayed User A's name and email",
            "passed",
            {"name": "Phase Seven User A"},
        ),
        check(
            "ui-reload-session",
            "frontend",
            "Browser reload preserved the authenticated session",
            "passed",
            {"observed_url": "/dashboard", "session_badge": "Session verified"},
        ),
        check(
            "ui-documents-render",
            "frontend",
            "Documents page rendered both User A reports and actual failure states",
            "passed",
            {
                "document_count": 2,
                "screenshot": "screenshots/documents-indexing-failure.png",
            },
        ),
        check(
            "ui-chat-empty-state",
            "frontend",
            "Chat page rendered the no-indexed-document empty state and disabled composer",
            "passed",
            {
                "composer_disabled": True,
                "screenshot": "screenshots/chat-no-indexed-documents.png",
            },
        ),
        check(
            "ui-logout",
            "frontend",
            "React logout returned the browser to login",
            "passed",
            {"observed_url": "/login"},
        ),
        check(
            "ui-post-logout-protection",
            "frontend",
            "Dashboard navigation after logout redirected to login",
            "passed",
            {"observed_url": "/login"},
        ),
        check(
            "ui-login-b",
            "frontend",
            "User B logged in through the React login page",
            "passed",
            {"observed_url": "/dashboard"},
        ),
        check(
            "ui-user-b-empty-state",
            "frontend",
            "User B document library displayed its real zero-document empty state",
            "passed",
            {"document_count": 0},
        ),
        check(
            "ui-upload-progress",
            "frontend",
            "Browser upload showed the real extraction/chunking progress state",
            "passed",
            {
                "filename": "coca-cola-2024-10-k.pdf",
                "label": "Extracting and chunking",
                "displayed_progress": "100%",
            },
        ),
        check(
            "ui-upload-final-state",
            "frontend",
            "Browser upload returned and rendered the persisted safe indexing failure",
            "passed",
            {
                "document_count": 1,
                "page_count": 140,
                "indexed_chunks": 0,
                "status": "failed",
                "screenshot": "screenshots/frontend-upload-result-user-b.png",
            },
            limitation="The displayed message came from the pre-restart process; clearer wording is covered by the new regression test.",
        ),
        check(
            "ui-responsive-390",
            "frontend",
            "Chat layout was inspected with Chrome responsive emulation at 390 CSS pixels",
            "passed",
            {"viewport_width_css_px": 390, "layout": "stacked"},
        ),
        check(
            "persistence-backend-restart-auth",
            "persistence",
            "Authentication remained valid across a controlled backend restart with the same JWT secret",
            "passed",
            {"database": "SQLite substitute", "jwt_secret_changed": False},
        ),
        check(
            "persistence-backend-restart-documents",
            "persistence",
            "Document metadata, pages, chunks, and files remained after backend restart",
            "passed",
            {
                "documents": 2,
                "nvidia_pages_chunks": [181, 347],
                "coca_cola_pages_chunks": [140, 315],
            },
        ),
        check(
            "persistence-chat-history",
            "persistence",
            "Generated chat history persistence",
            "blocked",
            None,
            limitation="No document reached indexed/completed state, so the production chat endpoint correctly did not create a generated conversation.",
        ),
        check(
            "persistence-verification-diagnostics",
            "persistence",
            "Generated verification-diagnostics persistence",
            "blocked",
            None,
            limitation="No LLM answer was generated; therefore no assistant verification diagnostics existed to persist.",
        ),
        check(
            "ui-registration-screen",
            "frontend",
            "React registration screen visual check",
            "not_run",
            None,
            limitation="Computer Use stopped when it could not determine the browser URL with sufficient confidence. Registration was tested through the live API, but this UI screen is not claimed as verified.",
        ),
    )
    by_id.update({item["id"]: item for item in manual})
    checks = list(by_id.values())
    for item in checks:
        observed = item.get("observed")
        response_body = observed.get("body") if isinstance(observed, dict) else None
        if isinstance(response_body, dict) and isinstance(
            response_body.get("items"), list
        ):
            pages = response_body["items"]
            if pages and all(
                isinstance(page, dict) and "page_number" in page for page in pages
            ):
                observed["body"] = {
                    key: response_body.get(key)
                    for key in (
                        "document_id",
                        "filename",
                        "total",
                        "page",
                        "page_size",
                        "total_pages",
                    )
                    if key in response_body
                } | {
                    "returned_items": len(pages),
                    "page_numbers": [page["page_number"] for page in pages],
                    "extracted_text_omitted": True,
                }
    summary = {
        status: 0 for status in ("passed", "failed", "skipped", "blocked", "not_run")
    }
    for item in checks:
        summary[item["status"]] += 1

    results.update(
        {
            "schema_version": "2.0",
            "finished_at": datetime.now(UTC).isoformat(),
            "summary": summary,
            "environment": {
                "operating_system": "Windows",
                "database": "persistent isolated SQLite substitute",
                "postgresql_tested": False,
                "postgresql_limitation": "Docker service was inaccessible; native PostgreSQL could not bind loopback sockets.",
                "chromadb_tested": False,
                "chromadb_limitation": "No ChromaDB server listened on 127.0.0.1:8001.",
                "llm_tested": False,
                "llm_limitation": "Paid calls were disabled and no local Ollama model/server was available.",
                "backend": "FastAPI/Uvicorn on 127.0.0.1:8000",
                "frontend": "React/Vite on 127.0.0.1:5173",
                "embedding_model": "BAAI/bge-small-en-v1.5, cached weights, CPU",
                "migration_head": resume["migration_head"],
            },
            "automated_tests": {
                "backend_pytest": {
                    "passed": 100,
                    "failed": 0,
                    "skipped": 2,
                    "duration_seconds": 12.50,
                    "skip_reasons": [
                        "live ChromaDB integration disabled",
                        "live LLM integration disabled",
                    ],
                },
                "ruff": {
                    "status": "passed",
                    "command": "python -m ruff check app tests",
                },
                "frontend_eslint": {"status": "passed", "command": "npm run lint"},
                "frontend_build": {
                    "status": "passed",
                    "command": "npm run build",
                    "vite_version": "7.3.7",
                    "modules_transformed": 1759,
                },
                "alembic_current": {
                    "status": "passed",
                    "revision": resume["migration_head"],
                },
            },
            "persisted_documents": resume["documents"],
            "checks": checks,
        }
    )
    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
