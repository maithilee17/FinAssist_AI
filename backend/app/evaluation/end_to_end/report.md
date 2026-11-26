# FinAssist AI Phase 7.2 End-to-End Report

Date: 6 November 2026 (Asia/Calcutta)

## Outcome

Phase 7.2 is partially complete. The available local application paths were exercised end to end, including real authentication, multipart PDF upload, PyMuPDF extraction, chunk persistence, ownership enforcement, browser reload/logout, upload progress, safe no-index chat behavior, and persistent relational/file storage.

Critical production integrations remain blocked: live PostgreSQL, live ChromaDB, and an LLM provider. Therefore vector indexing, grounded answer generation, citations, evidence/confidence rendering, successful vector-aware document deletion, and generated-chat persistence are not validated.

Machine-readable E2E checks: **72 passed, 0 failed, 0 skipped, 7 blocked, 1 not run**. Automated backend tests are reported separately: **100 passed, 0 failed, 2 skipped**.

## 1. Environment inventory

| Component | Observed environment | Result |
|---|---|---|
| OS | Windows | Used |
| Python | 3.11.2 | Used |
| FastAPI | 0.162.0 | Used |
| SQLAlchemy | 2.1.6 async | Used |
| Database | SQLite 3.39.4, persistent isolated file | Substitute only |
| PostgreSQL | 17.10 client/binaries | Blocked: native server could not bind loopback |
| Docker | CLI 29.6.1 | Blocked: Docker service inaccessible |
| Chroma | HTTP client 1.5.9 | Blocked: no live server on port 8001 |
| Embeddings | cached `BAAI/bge-small-en-v1.5`, CPU | Executed |
| Ollama | client 0.32.14 | Blocked: no running server/model |
| Node / npm | 26.3.0 / 9.9.4 | Used |
| Frontend | React/Vite 7.3.7 | Executed |

No paid LLM calls were enabled.

## 2. Database and migrations

- The isolated SQLite database is `backend/app/evaluation/end_to_end/.runtime/finassist-e2e.db`.
- Alembic upgrade completed through `20261103_0005`.
- `alembic current` reported `20261103_0005 (head)`.
- Two users, three document records, 461 extracted page rows, and 977 chunk rows remain persisted.
- PostgreSQL-specific migration/runtime behavior was not tested.

## 3. Authentication

The running API verified registration for two accounts, duplicate rejection, valid login, generic invalid-password rejection, `/api/auth/me`, HttpOnly auth-cookie behavior, readable CSRF token cookie, missing-CSRF rejection, unauthenticated API rejection, logout, and post-logout rejection.

The browser verified protected-route redirect, User A and User B login, authenticated identity, cookie-backed reload, logout, and post-logout protection. Authentication and document records remained available across a controlled backend restart using the same JWT secret. The React registration screen visual check is `not_run` because Computer Use stopped when it could not verify the browser URL safely; registration itself passed through the real API.

## 4. Document upload and processing

| Owner | Document | Upload path | Pages | Chunks | File | Indexing |
|---|---|---:|---:|---:|---|---|
| User A | NVIDIA FY2025 Annual Report | API multipart | 181 | 347 | 49,970,589 bytes, present | Failed safely; 0 indexed |
| User A | Coca-Cola 2024 Form 10-K | API multipart | 140 | 315 | 1,354,777 bytes, present | Failed safely; 0 indexed |
| User B | Coca-Cola 2024 Form 10-K | React browser upload | 140 | 315 | 1,354,777 bytes, present | Failed safely; 0 indexed |

All page sequences were verified as one-based and contiguous. API responses did not expose storage paths. Retry reused retained chunks; it did not re-extract the PDF. The browser upload displayed the real `Extracting and chunking…` progress state and then rendered the persisted failed-indexing card.

Successful indexing is not claimed. ChromaDB was unreachable, and each document correctly remained `failed` with `indexed_chunk_count = 0` and `indexed_at = null`.

Deletion was attempted by the owner. It returned HTTP 503 because vector cleanup could not be guaranteed; relational rows, chunks, and PDFs intentionally remained. Cross-user deletion returned 404 before vector-store access. No successful deletion/cleanup is claimed.

## 5. Chat

Six live API questions were executed: exact numerical, conceptual, period comparison, multi-passage, missing information, and multi-document. Each returned HTTP 409 with `No indexed documents are available for this account`.

This is the correct safe behavior for the environment and no chat session was created. It validates the no-index guard but does not validate generated answers, retrieval diagnostics, citations, excerpts, verification status, confidence, answer latency, or LLM correctness. The browser independently displayed the chat empty state and disabled composer.

## 6. Cross-user security

- User B could not inspect, read pages, retry, delete, or select User A's NVIDIA document.
- After the browser upload, User A could not inspect, read pages/chunks, retry, delete, or select User B's Coca-Cola document.
- Document lists returned only the authenticated owner's records.
- A database-seeded chat-session fixture was readable/deletable by its owner and returned 404 to the other user. The fixture was deleted after the test.
- Unauthenticated profile, document-list, and chat-list requests returned 401.
- State-changing cookie requests without CSRF returned 403.

No security issue was discovered in these tested ownership paths.

## 7. Persistence

Browser reload preserved authentication. A controlled backend restart with the same JWT secret preserved authentication plus document metadata, extracted pages, chunks, and original files. Cancelled deletion preserved all data consistently.

Generated chat-history persistence and verification-diagnostics persistence are blocked because no document reached indexed/completed state and no answer was generated. Deleted-document absence is also blocked because safe deletion correctly cancelled at the unavailable vector-store boundary.

## 8. Frontend

Directly observed states:

- Login, protected navigation, authenticated dashboard, and logout.
- User A document list and indexing errors.
- User B zero-document empty state.
- Real Coca-Cola upload progress and final safe failure card.
- Chat no-indexed-document empty state and disabled composer.
- Responsive chat layout inspected at 390 CSS pixels.

Chat response bubbles, citation expansion, and verification/confidence indicators were not reachable without indexed vectors and an LLM. They are covered by source/unit tests but are not claimed as browser-verified.

Screenshots are stored in `screenshots/`:

- `dashboard-authenticated.png`
- `documents-indexing-failure.png`
- `chat-no-indexed-documents.png`
- `frontend-upload-result-user-b.png`

## 9. Automated tests

| Gate | Result |
|---|---|
| Backend pytest | 100 passed, 2 skipped in 12.50 seconds |
| Ruff | Passed |
| Frontend ESLint | Passed |
| Frontend production build | Passed; 1,759 modules transformed |
| Alembic current | `20261103_0005 (head)` |

The two skips are explicit opt-in integrations: live ChromaDB and live LLM provider. An earlier sandboxed pytest attempt hung in an AnyIO thread-pool test; rerunning outside the restricted sandbox completed normally and is the reported result.

## 10. Bug discovered and fixed

When ChromaDB was unavailable during indexing, the UI displayed `Document vectors could not be deleted`. This leaked an internal idempotency step and incorrectly framed the failure as deletion.

`DocumentIndexingService` now distinguishes embedding failures from vector-store failures and returns the safe message: `The vector store is unavailable; document indexing could not be completed`. A regression test asserts the new indexing context and prevents the misleading word `deleted` from returning.

The screenshot contains the old message because it was captured from the already-running pre-restart process. The code fix and regression test are the authoritative post-fix evidence.

## 11. Remaining limitations

- PostgreSQL was not tested; SQLite is not equivalent to PostgreSQL.
- Live ChromaDB indexing, semantic retrieval, hybrid retrieval against the live store, and vector deletion were not tested.
- No OpenAI or Ollama generation occurred.
- Generated-answer correctness, citations, evidence verification, confidence UI, and LLM latency were not tested.
- Generated chat-history and verification-diagnostics persistence were not tested.
- Successful document deletion could not be completed because the application deliberately requires vector cleanup first.
- The React registration screen was not visually verified in the final browser pass.

## 12. Reproduction

See `reproducibility.md` for exact environment variables and commands. The principal commands are:

```powershell
cd backend
.\.venv\Scripts\python.exe app\evaluation\end_to_end\runner.py
.\.venv\Scripts\python.exe app\evaluation\end_to_end\resume_checks.py
.\.venv\Scripts\python.exe app\evaluation\end_to_end\finalize_results.py
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m ruff check app tests

cd ..\frontend
npm run lint
npm run build
```

