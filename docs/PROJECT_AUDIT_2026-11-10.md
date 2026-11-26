# FinAssist AI Complete Repair Audit — 2026-11-10

## Scope and verification boundary

This audit traced upload, extraction, relational chunk persistence, BGE inference,
Chroma upsert/count verification, retry/deletion, adaptive retrieval, evidence and
claim verification, chat persistence, and React status rendering. No Docker command
or LLM request was executed. The operator's local ports 5173, 8000, and 8001 were not
listening during final verification, so live PostgreSQL, ChromaDB, container-image,
browser E2E, and generated-answer acceptance remain unverified.

## Discovered issues, root causes, and repairs

| Issue | Root cause | Repair and evidence |
| --- | --- | --- |
| Uploads failed with only “Document embeddings could not be generated” | `EmbeddingService`, `DocumentIndexingService`, and the upload router successively replaced the original exception; the expected indexing branch did not log a traceback | Stable diagnostic codes now preserve the failure stage, while `logger.exception` retains the backend exception chain without logging chunk text |
| Container model cache could be unwritable | Compose mounted `/app/model-cache`, but the non-root image user did not own a newly created or pre-existing named volume | A minimal root entrypoint creates/chowns only uploads and model-cache, then drops to `finassist` with `gosu`; no persisted data is deleted |
| Invalid model output could reach Chroma | Count, dimensions, finite values, zero vectors, and normalization were not validated | Embeddings now fail closed and verify one normalized 384-dimensional finite vector per non-empty chunk |
| Runtime/model compatibility could drift across rebuilds | Torch and Sentence Transformers were broad ranges and could resolve different CPU/CUDA combinations | Docker installs pinned Torch 2.10.0 from the official CPU index and Sentence Transformers 5.7.0; BGE revision and expected dimension are configurable and pinned by default |
| A partial Chroma write could leave orphaned vectors | Indexing raised immediately after upsert/count failure without document-scoped compensation | The indexing service attempts authenticated document cleanup before failing and retains PostgreSQL pages/chunks for retry |
| Vector failures lacked operation context | Chroma client, collection, upsert, query, count, delete, and heartbeat errors used generic exceptions | Safe operation-specific messages and backend tracebacks were added; vectors and queries are validated before network calls |
| A clean database could serve requests before migrations | Compose launched Uvicorn directly | Backend startup runs idempotent `alembic upgrade head` before Uvicorn; no existing migration was edited and no new migration was needed |
| Build contexts could contain local caches/runtime data | Root `.dockerignore` does not apply when build contexts are `./backend` and `./frontend` | Context-specific ignore files exclude venvs, model caches, uploads, PDFs, SQLite files, evaluation runtime data, `node_modules`, and build output |
| A failed HTTP 201 upload looked partly successful | The upload endpoint intentionally preserves a failed record, but the UI treated every 201 as a neutral/success notice | Failed processing is rendered as an error with the safe backend diagnostic; completed state is labelled Indexed; retry reports its actual result |
| First model download could exceed the browser timeout | Upload timeout was fixed at 120 seconds | Processing timeout is configurable and defaults to 600 seconds; progress copy explicitly includes embedding/indexing |
| Corrupt PDF rejection returned 500 on Windows | A failed path-backed PyMuPDF constructor retained its native stream in the exception frame, so immediate cleanup raised `WinError 32` | The failing constructor is isolated in a narrow helper that releases its frame before deletion. Valid PDFs remain path-backed. The original failing API case and immediate-unlink regression now pass |
| Setup documentation could overwrite `.env` | `Copy-Item .env.example .env` was unconditional | PowerShell setup now copies only when `.env` is absent |

The exact historical container exception cannot be recovered because the old code
discarded it and the current services were stopped. Cache ownership is a confirmed
source defect and a strong container-only failure candidate, not a claim about an
unobserved traceback. If another cause remains, the repaired logs and diagnostic now
expose it.

## Embedding verification

The existing cached `BAAI/bge-small-en-v1.5` weights loaded locally on CPU with
network access disabled. The operator diagnostic generated two document vectors and
one query vector, all finite, normalized, and 384-dimensional. A separate real-model
integration test extracted a fictional two-page PDF into page-aware chunks and
generated normalized BGE embeddings: **1 passed in 20.28 seconds**.

This proves the model name, local cache, CPU inference, input path, and numeric
validation in the local Python environment. It does not prove that the rebuilt Docker
image or its named volume works until the operator rebuilds and runs it.

## Automated verification

| Check | Result |
| --- | --- |
| Complete backend pytest suite | **124 passed, 3 skipped, 0 failed** in 16.40 s, including the two demo-PDF tests |
| Fictional demo-PDF generator (focused run) | **2 passed, 0 failed** |
| Real cached BGE integration | **1 passed, 0 failed** in 20.28 s |
| Focused corrupt-PDF/upload cleanup | **9 passed, 0 failed** |
| Ruff lint (`app`, `tests`) | Passed |
| Formatting for all repaired/new files | Passed (14 files at that checkpoint; demo files also passed) |
| Full repository format check | Not claimed: preserved Phase 7.3 `performance/runner.py` has pre-existing format differences |
| Python dependency consistency (`pip check`) | Passed |
| Compose YAML parse | Passed; services: backend, chroma, frontend, postgres |
| Frontend unit tests | **3 passed, 0 failed** |
| Frontend ESLint | Passed |
| Frontend Vite production build | Passed; 1,760 modules, 377.27 kB JS (119.79 kB gzip), 37.32 kB CSS (7.13 kB gzip) |
| Live backend/frontend/Chroma probes | Blocked: all target ports actively refused connections |
| PostgreSQL/Chroma integration tests | Skipped/blocked because services were not running |
| LLM integration and generated-answer review | Skipped by policy; no provider call was made |

Opt-in skips are intentional: cached BGE, live Chroma, and configured LLM integrations
require explicit environment flags. The cached BGE integration was then enabled and
passed separately; Chroma and LLM remained disabled.

## Files changed in this repair audit

Modified:

- `.env.example`, `README.md`, `docker-compose.yml`
- `backend/Dockerfile`, `backend/requirements.txt`
- `backend/app/config.py`, `backend/app/services/rag_dependencies.py`
- `backend/app/routers/documents.py`
- `backend/app/services/embedding_service.py`
- `backend/app/services/indexing_service.py`
- `backend/app/services/vector_store.py`
- `backend/app/services/pdf_processor.py`
- `backend/tests/test_documents.py`, `test_embedding_service.py`,
  `test_indexing_service.py`, `test_pdf_processing.py`, `test_vector_store.py`
- `frontend/Dockerfile`, `frontend/package.json`
- `frontend/src/pages/DocumentsPage.jsx`

Added:

- `backend/.dockerignore`, `frontend/.dockerignore`
- `backend/docker-entrypoint.sh`
- `backend/app/diagnostics/__init__.py`
- `backend/app/diagnostics/embedding.py`
- `backend/app/diagnostics/demo_pdf.py`
- `backend/tests/test_embedding_integration.py`
- `backend/tests/test_demo_pdf.py`
- `frontend/src/lib/documentStatus.js`
- `frontend/tests/documentStatus.test.js`
- `docs/EMBEDDING_TROUBLESHOOTING.md`
- `docs/PROJECT_AUDIT_2026-11-10.md`

No Alembic migration was added or changed because these repairs do not alter the
database schema. The existing expected head remains `20261103_0005`.

## Operator acceptance commands (PowerShell)

The following commands are documentation for the operator; Codex did not execute
them during this audit.

```powershell
Set-Location 'C:\Users\Mihir\Desktop\Placement prep\project\FinAssist AI'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: use a strong POSTGRES_PASSWORD and JWT_SECRET_KEY.

docker compose build backend frontend
docker compose up -d
docker compose exec backend alembic current
docker compose exec backend python -m app.diagnostics.embedding
docker compose exec backend python -m app.diagnostics.embedding --local-files-only

Invoke-RestMethod http://localhost:8000/api/health/live
Invoke-RestMethod http://localhost:8000/api/health/ready
Invoke-RestMethod http://localhost:8001/api/v2/heartbeat
```

Expected migration output includes `20261103_0005 (head)`. Both embedding diagnostics
must report `ok`, dimension 384, finite vectors, and a writable cache before retrying a
failed document. If they fail, inspect the full safe traceback:

```powershell
docker compose logs backend --tail 250
```

Do not delete database, Chroma, upload, or model-cache volumes as a repair shortcut.

## Manual upload-to-answer acceptance

1. Generate the fictional report (this command refuses overwrite):

   ```powershell
   Set-Location 'C:\Users\Mihir\Desktop\Placement prep\project\FinAssist AI\backend'
   .\.venv\Scripts\python.exe -m app.diagnostics.demo_pdf ..\fictional-financial-report.pdf
   ```

2. Open `http://localhost:5173`, register/login, and upload the generated PDF.
3. Confirm the status progresses through processing/indexing to **Indexed**, pages = 3,
   and indexed chunks > 0. A failed record must show its diagnostic and remain retryable.
4. Ask `What was total revenue in FY2025?`; review USD 125.5 million and page 1.
5. Ask `Compare FY2024 and FY2025 operating profit.`; review USD 20.0 million and
   USD 25.1 million with page 2 evidence.
6. Ask `What risks did management identify?`; review page 3 citations.
7. Ask `What was the debt-to-equity ratio?`; the report says it was not disclosed, so
   the answer must not invent a ratio.
8. Inspect retrieval strategy, evidence status, confidence explanation, excerpts, and
   chat persistence. Repeat with a second account to confirm ownership isolation.
9. Delete the document and verify PostgreSQL metadata, private PDF, relational chunks,
   and Chroma vectors are removed without affecting the other account.

Generated-answer correctness and citation correctness must not be accepted until a
real provider is explicitly configured and these answers are manually reviewed.

## Remaining limitations

- Docker image build, entrypoint permissions, live PostgreSQL migration, and live
  Chroma upsert/query/delete/persistence are source-reviewed but not executed here.
- No browser E2E acceptance ran because the frontend/backend ports were stopped.
- No LLM call ran, so generated answer quality, provider latency, and provider failure
  behavior are covered only by mocks/unit tests.
- Scanned image-only PDFs are detected as having little/no extractable text; OCR is not
  implemented.
- A Hugging Face download still needs outbound network access on the first uncached
  run. Authentication is optional for this public model but can improve rate limits.
- The repository has no commit baseline and all project files appear untracked; follow
  `docs/RELEASE_BASELINE.md` before the first commit.
