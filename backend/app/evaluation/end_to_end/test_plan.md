# FinAssist AI Phase 7.2 Test Plan

## Scope and truth criteria

This plan exercises the running FastAPI and React applications. A workflow is marked passed only when an HTTP response, persisted database/file artifact, or observed browser state supports it. Source inspection alone is not a pass.

The available environment cannot run PostgreSQL, ChromaDB, or Ollama. Persistent SQLite is used only as a documented relational test substitute. Vector indexing, generated answers, citations, verification panels, and successful vector-aware deletion therefore remain blocked.

## Environment checks

| Area | Planned check | Pass criterion |
|---|---|---|
| Backend | Liveness and readiness | Liveness returns 200; readiness accurately identifies unavailable dependencies |
| PostgreSQL | Docker/native availability | Record the actual availability; do not substitute a pass |
| Database | Alembic migration | Isolated database reaches the repository head revision |
| ChromaDB | Service health | Record unavailable if no live service is reachable |
| LLM | Provider health | No paid calls; record unavailable when Ollama is not running |
| Storage | Private upload root | Files exist under the configured backend-only root and paths are not returned by APIs |

## Authentication and security

- Register Users A and B.
- Reject duplicate registration and incorrect credentials.
- Validate `/api/auth/me`, HttpOnly auth cookie, readable CSRF cookie, and missing-CSRF rejection.
- Verify cookie-backed reload, logout, post-logout route protection, and controlled restart behavior.
- Reject unauthenticated document and chat requests.
- Verify both ownership directions with real documents where available.
- Verify User A cannot inspect, retry, delete, or select User B's document for retrieval.
- Verify chat session ownership with an isolated database fixture when generation is unavailable.

## Document workflows

Reports:

1. NVIDIA FY2025 Annual Report (181 PDF pages, 49,970,589 bytes).
2. The Coca-Cola Company 2024 Form 10-K (140 PDF pages, 1,354,777 bytes).

Checks:

- Upload by real multipart request.
- Upload Coca-Cola through the browser and observe progress.
- Confirm document metadata, private file existence and size, page rows, chunk rows, page numbering, and ownership.
- Confirm NVIDIA produces 181 pages and 347 chunks.
- Confirm Coca-Cola produces 140 pages and 315 chunks.
- Retry from retained chunks without re-extraction.
- Confirm Chroma failure leaves the document failed rather than falsely completed.
- Confirm deletion cancels safely when vector cleanup cannot be guaranteed.

## Chat workflows

Submit these categories through the live API:

- Exact numerical: NVIDIA FY2025 revenue.
- Conceptual: factors affecting Coca-Cola operating margins.
- Period comparison: NVIDIA FY2024 versus FY2025 revenue.
- Multi-passage: data-center growth and supply risk.
- Missing information: NVIDIA FY2027 debt-to-equity ratio.
- Multi-document: NVIDIA and Coca-Cola business risks.

With no indexed documents, the required safe outcome is HTTP 409 with no fabricated answer or persisted conversation. Generated-answer, citation, confidence, verification, and LLM-latency checks are blocked, not passed.

## Persistence

- Reload the authenticated React application.
- Restart the backend with the same JWT secret.
- Verify authentication, document metadata, extracted pages, chunks, and files remain readable.
- Verify a cancelled deletion leaves all data intact.
- Mark generated chat history and verification-diagnostics persistence blocked if no answer can be produced.

## Frontend

- Login and protected-route redirects.
- Authenticated dashboard identity.
- Document empty/list/error states.
- Browser upload progress and final safe failure.
- Chat no-indexed-document empty state and disabled composer.
- Logout and post-logout protection.
- Responsive inspection at 390 CSS pixels.
- Registration screen, chat answer cards, citation expansion, and verification UI only pass if directly observed.

## Automated gates

- `pytest -q -rs`
- `ruff check app tests`
- `npm run lint`
- `npm run build`
- `alembic current` against the isolated Phase 7.2 database

