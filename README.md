# FinAssist AI

## Product and deployment guides

- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Embedding and indexing diagnostics](docs/EMBEDDING_TROUBLESHOOTING.md)
- [Complete repair audit (2026-11-10)](docs/PROJECT_AUDIT_2026-11-10.md)
- [UI walkthrough and user guide](docs/UI_WALKTHROUGH.md)
- [Environment configuration](docs/ENVIRONMENT_CONFIGURATION.md)
- [Production deployment checklist](docs/PRODUCTION_DEPLOYMENT_CHECKLIST.md)
- [Staging acceptance checklist](docs/STAGING_ACCEPTANCE.md)
- [Browser E2E test plan](docs/BROWSER_E2E_PLAN.md)
- [Safe initial Git baseline](docs/RELEASE_BASELINE.md)
- [Operations and observability](docs/OPERATIONS_AND_OBSERVABILITY.md)
- [Security and privacy notes](docs/SECURITY_PRIVACY.md)
- [Phase 7.5 security review](docs/PHASE_7_5_SECURITY_REVIEW.md)
- [Placement and interview guide](docs/PLACEMENT_GUIDE.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Phase 7.4 verification report](docs/PHASE_7_4_VERIFICATION.md)
- [Phase 7.5 verification report](docs/PHASE_7_5_VERIFICATION.md)

FinAssist AI is an adaptive, evidence-aware financial document question-answering system. It is being built as a full-stack application with React, FastAPI, PostgreSQL, ChromaDB, hybrid retrieval, and confidence-aware answer generation.

> Current status: **The complete repair audit is verified for locally executable scope.** Core application, real-report evaluation, environment-limited E2E checks, performance work, UI/security polish, and the repaired embedding diagnostics are documented. Live acceptance remains blocked until the operator starts PostgreSQL, ChromaDB, the application services, and the local Ollama service.

## Project at a glance

FinAssist solves a specific problem: financial questions need answers that can be traced to the user's own reports. The system routes exact financial terms to BM25, conceptual language to BGE semantic search, and mixed/comparison questions to a hybrid RRF ranking. It verifies that the evidence covers the requested metric and period before generation, validates material claims and citations afterward, and abstains when support is missing.

The 16-case real-world evaluation used two official reports, 662 chunks, and cached normalized production BGE vectors. It reported 0.875 exact evidence-outcome accuracy, 0.700 citation-page correctness on answerable cases, and 668.170 ms mean pipeline latency without an LLM. Generated-answer correctness was not measured because provider calls were disabled. These are small-dataset observations, not general accuracy guarantees.

## Architecture

```text
Browser (React + Vite)
        |
        | HTTPS / JSON REST API; HttpOnly JWT cookie or Bearer JWT
        v
FastAPI application
  |-- authentication and authorization
  |-- document metadata and chat history --------> PostgreSQL
  |-- PDF extraction / chunking / BGE embeddings
  |-- adaptive router --> BM25 / BGE+Chroma / RRF
  |-- evidence requirements + bounded retrieve-more
  |-- grounded answer generation ----------------> Local Ollama /api/chat
  `-- claim/citation verification + confidence policy
```

PostgreSQL is the source of truth for users, ownership, documents, sessions, and messages. ChromaDB contains chunks and vectors with `user_id`, `document_id`, filename, page, and section metadata. Every retrieval request is filtered by the authenticated user's identifiers. Uploaded PDFs are treated as untrusted data: their text is evidence, never system instructions.

### Authentication architecture

Passwords are hashed with Argon2 through `pwdlib` and the hash is the only password-derived value stored. Login creates a signed JWT containing `sub`, `iat`, `exp`, `jti`, `iss`, `aud`, and an access-token type. The API accepts that JWT either as a Bearer token or from an HttpOnly cookie.

The React application uses only the cookie-backed session and restores it through `GET /api/auth/me`; it does not save the JWT in localStorage or sessionStorage. Axios enables credentialed requests. A separate readable, random CSRF cookie must match the `X-CSRF-Token` header for authenticated state-changing cookie requests. Production deployments must use HTTPS with `COOKIE_SECURE=true`.

### Database schema

| Table | Important columns | Relationships |
|---|---|---|
| `users` | UUID `id`, `full_name`, unique/indexed `email`, `hashed_password`, `is_active`, timestamps | Owns documents and chat sessions |
| `documents` | UUID `id`, `user_id`, filename, private storage path, size, page count, processing/indexing state, embedding model, indexed count/timestamp | Belongs to one user; cascade delete |
| `document_pages` | UUID, document FK, page number, extracted text, character count, empty flag, extraction metadata | Unique page number per document |
| `document_chunks` | Stable UUID, document/user FKs, index, text, estimated tokens, represented page numbers | Relational source of truth for Chroma indexing |
| `chat_sessions` | UUID `id`, `user_id`, `title`, `created_at` | Belongs to one user; owns messages |
| `chat_messages` | UUID, session FK, role, message, structured sources, model/timing/retrieval metadata, timestamp | Belongs to one chat session; cascade delete |

Foreign keys and frequently filtered ownership/timestamp columns are indexed. Application models use portable SQLAlchemy UUID types while PostgreSQL remains the production database.

### Document processing architecture

```text
Authenticated multipart upload
        |
        | extension + MIME + streaming size checks
        v
Private filesystem (.part -> atomic rename)
        |
        | PDF header + PyMuPDF structural validation
        v
Document row: uploaded -> processing
        |
        | block-based, page-by-page Unicode extraction
        v
Conservative financial text cleaning
        |
        | paragraph-preferred chunking with overlap
        v
document_pages + document_chunks
        |
        v
Document row: indexing
        |
        | normalized BGE document embeddings + stable Chroma upsert
        v
verified vector count -> completed, or failed with retryable relational chunks
```

PyMuPDF extracts sorted text blocks to retain paragraph boundaries where possible. Empty pages are stored rather than silently discarded. Cleaning preserves currency symbols, decimal points, negative values, percentages, financial years, dates, and table-like spacing. Scanned image-only pages remain empty in Phase 3 because OCR is not enabled yet.

Chunk IDs are deterministic UUIDs derived from the document, chunk index, page references, and content digest. Chunks target `CHUNK_SIZE_TOKENS` estimated tokens with `CHUNK_OVERLAP_TOKENS` overlap. Each chunk stores every represented page number and is scoped to one user and one document.

Original PDFs live only beneath `UPLOAD_DIR`, which is mounted as a private backend volume and is never exposed through a static route. Database APIs never return storage paths. A failed indexing attempt retains its PDF, pages, and relational chunks; retry indexes those existing chunks without requiring another upload.

### Semantic RAG architecture

`BAAI/bge-small-en-v1.5` is loaded once per backend process. Document and query embeddings use the same model, normalized vectors, and the configured BGE query instruction. Chroma stores stable chunk IDs, text, filename, page numbers, and mandatory user/document metadata.

Every query first verifies document ownership and completed indexing in PostgreSQL. Chroma search always includes a server-side `user_id` filter plus optional document filters. Retrieved metadata—not LLM-written citations—builds the structured source list.

The configured provider is the local Ollama `/api/chat` endpoint. System instructions are sent separately from evidence, and extracted PDF text is delimited as untrusted content. Retrieval below `RAG_MIN_SIMILARITY` produces a deterministic insufficient-information response without calling the LLM.

### Adaptive hybrid retrieval

The rule-based query analyzer detects financial periods, numeric and currency references, named companies, metrics, regulatory terms, comparisons, and conceptual language without making another paid LLM call. Exact financial facts route to BM25, conceptual or descriptive questions route to semantic search, and mixed-context or comparison questions route to both systems.

BM25 indexes are built from completed, indexed relational `document_chunks`, cached per user, and invalidated when that user's documents are uploaded, retried, reindexed, or deleted. Selected-document filtering happens after the user-scoped index is loaded. Semantic search continues to enforce the authenticated `user_id` inside Chroma queries.

Hybrid mode combines ranks—not incomparable raw BM25 and cosine scores—using Reciprocal Rank Fusion with `RRF_CONSTANT=60`. Stable chunk UUIDs remove duplicates and preserve the filename, page list, excerpt, and component ranks. The RAG prompt and citation builder continue to consume actual ranked chunk metadata.

### Evidence-aware answer policy

The Phase 5 query analysis is extended into structured requirements: requested financial metrics, reporting periods, companies, comparison values, units, and conceptual disclosure topics. The evidence verifier combines lexical relevance with explicit requirement coverage and validates that every passage has the authenticated user, an allowed document ID, a stable chunk ID, a filename, and positive page references. Vector similarity alone never establishes sufficiency.

Evidence has three states:

- `sufficient` permits one grounded generation call.
- `weak` expands top-k in bounded steps, deduplicates by stable chunk UUID, reranks through the existing adaptive strategy, and verifies again.
- `insufficient` returns a deterministic abstention without calling the LLM.

After generation, material claims are split and checked independently for financial metrics, exact numbers, reporting periods, lexical entailment, and valid `[Source N]` references. Unsupported sentences are removed once without making another provider call. If no supported material claim remains, the answer is replaced with an abstention. Returned source cards still come exclusively from actual retrieved chunks.

The confidence score combines retrieval relevance (30%), evidence sufficiency (35%), claim support (25%), and citation validity (10%), then applies a low-confidence safety cap when evidence or claims are unsupported. It is explicitly labelled a deterministic evidence-quality score, not a calibrated probability of truth.

## Ollama-only deployment

The only supported generation provider is `LLM_PROVIDER=ollama`. No external LLM
API key is required. BGE embeddings and ChromaDB remain unchanged. See
[model selection and migration verification](docs/OLLAMA_MIGRATION_REPORT.md).

For native Windows startup, use `.\start.ps1` as documented below.
The older copied `backend/.venv` may point to another laptop: create a fresh virtual
environment for native development instead of reusing it.

Set `OLLAMA_NO_CLOUD=1` in the Windows Ollama server environment and restart Ollama
to disable its cloud features. The backend also rejects cloud model names and the
Ollama cloud endpoint. Do not put this server setting only in the backend container.

## Local quick start

### One-time Windows prerequisites

Install Docker Desktop with Compose v2 supporting `up --wait`, Windows Ollama,
and Git for Windows or an initialized WSL distribution if using Bash. Native
PowerShell needs neither Bash nor host Python/Node: all four application services
run in Docker. Keep this checkout on a Windows drive, including from WSL
(`/mnt/c/...`); Linux-filesystem WSL checkouts are deliberately rejected.

Keep the existing private `.env`. The manager never creates, edits, sources, or
prints it. The current installation uses `LLM_PROVIDER=ollama` and
`OLLAMA_MODEL=qwen3:4b-instruct`. The resolved Compose configuration is authoritative
for model, ports, build arguments and service dependencies. Install a missing
model manually, only when needed; the manager never runs `ollama pull`.

### One-command startup

From Git Bash (or WSL on the Windows-drive checkout):

```bash
./start.sh
```

From Windows PowerShell or PowerShell 7:

```powershell
.\start.ps1
```

Both entry points use `scripts/finassist-startup.ps1` for Windows host process,
network and Docker inspection. This avoids confusing a WSL process namespace or
localhost address with the Windows host. WSL also checks native project dev
servers in its own distribution before handing off. Windows interop must be
enabled in WSL. The scripts do not change PowerShell execution policy: use your
organization's normal trusted/signed-script policy if execution is blocked.

The default action checks dependencies/model availability, gracefully stops
verified previous project instances, cleans disposable caches, builds missing or
changed images, starts the entire Compose graph, and verifies readiness. A repeat
startup restarts project containers but reuses matching images. Concurrent
startup/stop operations are rejected by an OS-held lock; a leftover lock file is
harmless after the previous process exits. Legacy `start-finassist.*` files remain
available, but the new manager should be used consistently for these guarantees.

| Command | Action |
|---|---|
| `./start.sh` | Safe cleanup and complete startup |
| `./start.sh --restart` | Gracefully restart the project |
| `./start.sh --stop` | Stop only verified project containers/dev servers |
| `./start.sh --status` | Show services, resolved ports and health without launching Docker |
| `./start.sh --logs` | Print the latest 100 sanitized log lines |
| `./start.sh --logs --follow` | Follow sanitized logs; Ctrl+C leaves services running |
| `./start.sh --no-clean` | Skip cache cleanup |
| `./start.sh --deep-clean` | Also clear disposable dist/coverage output |
| `./start.sh --build` | Request image rebuilding explicitly |
| `./start.sh --help` | Help without Docker or `.env` access |

PowerShell accepts the same arguments, for example `.\start.ps1 --restart --build`.
Unknown arguments, conflicting actions, and incompatible cleanup options fail.

The actual stack is PostgreSQL 17, ChromaDB, FastAPI/Uvicorn, and React 19/Vite 7
built with `npm ci` and served by Nginx. There is no Redis, scheduler, or background
worker. Compose applies `alembic upgrade head` before Uvicorn and observes the
configured dependency health checks. No extra host application server is started.

With the current configuration the frontend is `http://localhost:5173`, backend
is `http://localhost:8000`, and API docs are `/docs`. These values are examples;
the manager prints actual URLs derived from resolved published ports. It validates
the frontend's API build argument and backend CORS origin against those URLs.
Container health, backend dependency readiness, frontend `/health`, and the
backend's own Ollama/model diagnostic must pass before `FINASSIST AI READY`.

### Cleanup, ownership and logs

Default cleanup covers source-tree `__pycache__`, pytest/mypy/Ruff caches, and
Vite caches (including `frontend/node_modules/.vite`). `--deep-clean` additionally
removes `frontend/dist`, `frontend/coverage`, and `backend/htmlcov`. It does not
remove `node_modules`, virtual environments, dependency lockfiles, `.env`, uploads,
database/Chroma storage, volumes, Ollama/BGE models, or historical logs. Cleanup
checks absolute paths and refuses symlinks/junctions; no global Docker pruning or
volume-removal operation is used.

Container ownership requires both the resolved Compose project label and matching
working-directory label. A same-name project from another directory is refused.
Host process shutdown requires a rooted Vite entry or explicit backend source/app
directory; generic `python -m uvicorn app.main:app` is not sufficient proof. Ports
owned by unverified processes block startup and show PID/name instead of being
killed. Graceful shutdown precedes bounded, ownership-checked termination.

Logs under `logs/` are ignored by Git. Each run produces startup/error logs and
one sanitized snapshot per service. Ongoing logs remain under Docker's supervision;
use `--logs --follow` to monitor them. Resolved sensitive environment values and
credential-bearing URLs are redacted. Do not publish logs without reviewing them.
On failure or Ctrl+C the lock is released; partial containers stay available for
diagnosis. Shared Ollama and Docker Desktop are not stopped by `--stop`.

### Timeouts and troubleshooting

Timeouts are configurable in the invoking shell, in seconds (1–3600):

| Variable | Default | Purpose |
|---|---:|---|
| `FINASSIST_DOCKER_TIMEOUT` | 120 | Docker Desktop engine readiness |
| `FINASSIST_READY_TIMEOUT` | 300 | Ollama/application health readiness |
| `FINASSIST_STOP_TIMEOUT` | 20 | Graceful project shutdown before termination |
| `FINASSIST_COMMAND_TIMEOUT` | 600 | Individual Docker operations, including builds |

For a slow first build, for example:

```bash
FINASSIST_COMMAND_TIMEOUT=1800 ./start.sh --build
```

```powershell
$env:FINASSIST_COMMAND_TIMEOUT = '1800'
.\start.ps1 --build
```

- **Docker unavailable:** startup tries the installed Docker Desktop executable
  and waits; status/stop/logs never launch it. Check daemon permissions and Docker
  Desktop's Windows integration. The manager requires the Windows Docker CLI;
  WSL hands Windows-drive operations to the Windows host rather than changing
  Docker contexts or daemon configuration.
- **Ollama unavailable/model missing:** check the configured API and installed
  model. An existing Ollama process is waited on, not duplicated. Existing
  `OLLAMA_HOST` is respected. `host.docker.internal` is translated to Windows
  loopback only for the host probe; the container's actual URL is independently
  tested. No firewall change, GPU forcing, broad API binding, or model download
  happens automatically.
- **Port conflict:** inspect the reported PID/container. Stop or reconfigure that
  application manually; unknown owners are never killed. Host dev servers without
  provable ownership must also be stopped manually.
- **Stale frontend/backend:** use `--build`. The ignored `.finassist-state/`
  image fingerprints include build inputs/arguments and image IDs; do not reuse
  the old launcher's differently formatted build-state files as proof of a build.
- **Not ready:** use `--status` and `--logs`; read the latest `logs/errors-*.log`.
  A healthy Uvicorn process alone does not establish database/Chroma/Ollama health.
- **Interrupted/partial startup:** diagnose with `--status`, then rerun or use
  `--stop`. No failure handler deletes persistent state.

Offline manager safety checks (mocked Docker/HTTP/processes, no live services):

```powershell
pwsh -NoProfile -File .\scripts\test-startup.ps1
```

Bash validation where the runtime is available:

```bash
bash -n start.sh scripts/wsl-processes.sh
shellcheck start.sh scripts/wsl-processes.sh  # optional installed tool
```

### Run applications directly

Start PostgreSQL and ChromaDB with Docker:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d postgres chroma
```

Backend (change `DATABASE_URL` and `CHROMA_HOST` in `.env` to use `localhost`, and set `CHROMA_PORT=8001`):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Verification

```powershell
cd backend
python -m pytest -q

cd ..\frontend
npm run lint
npm run build

cd ..
docker compose config
```

The liveness endpoint only checks the API process. The readiness endpoint checks PostgreSQL, ChromaDB, and the configured Ollama model and returns HTTP 503 with per-service diagnostics until all are available.

### Embedding diagnostic

Before uploading a large report, validate the actual CPU model and persistent cache:

```powershell
docker compose exec backend python -m app.diagnostics.embedding
docker compose exec backend python -m app.diagnostics.embedding --local-files-only
```

The public BGE model does not require a Hugging Face token. The diagnostic distinguishes cache permissions/download failures, inference failures, dimension mismatches, and invalid vectors. See [Embedding and indexing diagnostics](docs/EMBEDDING_TROUBLESHOOTING.md).

The default Docker build installs the official CPU-only Torch wheel and pins the verified Sentence Transformers runtime. It does not install a CUDA runtime.

### Fictional acceptance-test PDF

Generate a three-page report containing clearly labelled fictional values. The command refuses to overwrite an existing file:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.diagnostics.demo_pdf ..\fictional-financial-report.pdf
```

Upload `fictional-financial-report.pdf` through Documents. After indexing, useful manual questions are:

- `What was total revenue in FY2025?` (expected evidence: USD 125.5 million, page 1)
- `Compare FY2024 and FY2025 operating profit.` (expected evidence: USD 20.0 million and USD 25.1 million, page 2)
- `What risks did management identify?` (expected evidence: page 3)
- `What was the debt-to-equity ratio?` (the safe answer should say it was not disclosed)

These values exist only in the generated test PDF; they are not hardcoded into retrieval or answer generation.

## Authentication API

### Register

`POST /api/auth/register`

```json
{
  "full_name": "Mihir Sharma",
  "email": "mihir@example.com",
  "password": "SecureFinance123!"
}
```

Returns HTTP 201 and the safe user profile. Duplicate normalized emails return HTTP 409. Passwords require 12–128 characters and at least three of lowercase, uppercase, number, and special-character groups.

### Login

`POST /api/auth/login`

```json
{
  "email": "mihir@example.com",
  "password": "SecureFinance123!"
}
```

Returns token metadata, the safe user profile, and an access JWT for non-browser API clients. It also sets the JWT as an HttpOnly cookie for the React application. Unknown emails and incorrect passwords intentionally return the same HTTP 401 message.

### Current user and logout

- `GET /api/auth/me` accepts the HttpOnly cookie or `Authorization: Bearer <token>`.
- `POST /api/auth/logout` clears both authentication cookies. Cookie-authenticated requests must send `X-CSRF-Token` matching the CSRF cookie.

Example API-client workflow:

```powershell
$registration = @{
  full_name = "Mihir Sharma"
  email = "mihir@example.com"
  password = "SecureFinance123!"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/register `
  -ContentType application/json -Body $registration

$login = @{ email = "mihir@example.com"; password = "SecureFinance123!" } | ConvertTo-Json
$auth = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login `
  -ContentType application/json -Body $login

Invoke-RestMethod -Uri http://localhost:8000/api/auth/me `
  -Headers @{ Authorization = "Bearer $($auth.access_token)" }
```

## Document API

All endpoints require the authenticated cookie session or a Bearer JWT. Cookie-authenticated upload, retry, and delete requests also require the CSRF header automatically supplied by the React client.

- `POST /api/documents/upload` — validate, privately store, extract, chunk, embed, and index a PDF.
- `GET /api/documents?page=1&page_size=20` — paginated current-user document list.
- `GET /api/documents/{document_id}` — safe metadata for one owned document.
- `GET /api/documents/{document_id}/status` — processing state and safe error.
- `GET /api/documents/{document_id}/pages?page=1&page_size=25` — owned extracted pages.
- `POST /api/documents/{document_id}/retry` — retry a failed document when its original PDF remains available.
- `DELETE /api/documents/{document_id}` — remove metadata, pages, chunks, and private PDF.

Documents belonging to another user are returned as HTTP 404 to avoid leaking their existence.

Example Bearer-token upload:

```powershell
$login = @{ email = "mihir@example.com"; password = "SecureFinance123!" } | ConvertTo-Json
$auth = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login `
  -ContentType application/json -Body $login

$headers = @{ Authorization = "Bearer $($auth.access_token)" }
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/documents/upload `
  -Headers $headers -Form @{ file = Get-Item .\annual-report.pdf }
```

Example upload response:

```json
{
  "id": "5cd36ea1-2bc1-4527-999e-c6f159d777e3",
  "filename": "annual-report.pdf",
  "file_size": 1824301,
  "mime_type": "application/pdf",
  "page_count": 96,
  "processing_status": "completed",
  "processing_error": null,
  "indexed_chunk_count": 143,
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "indexed_at": "2026-11-03T12:00:04Z",
  "upload_date": "2026-11-03T12:00:00Z",
  "updated_at": "2026-11-03T12:00:04Z"
}
```

## Chat API

- `POST /api/chat/ask` — adaptive keyword, semantic, or hybrid retrieval and grounded generation across all owned documents or a selected set.
- `GET /api/chat/sessions` — paginated owned conversation list.
- `GET /api/chat/sessions/{session_id}` — messages with persisted structured sources.
- `DELETE /api/chat/sessions/{session_id}` — delete an owned conversation.

```json
{
  "question": "What was the company's revenue in FY2025?",
  "document_ids": ["5cd36ea1-2bc1-4527-999e-c6f159d777e3"]
}
```

## Financial Analytics Dashboard API

The dashboard endpoint extracts verified, structured multi-year financial tables from indexed documents, executes deterministic calculations with exact `Decimal` precision, and returns executive KPI cards, longitudinal trend points, and grounded AI summaries.

- `GET /api/dashboard/{document_id}` — returns executive KPIs, revenue trends, profitability breakdowns, margin trajectories, and table-grounded summaries for an owned document.

Access control strictly enforces multi-tenant isolation; attempting to access another user's document returns HTTP 404.

Example response:

```json
{
  "document_id": "a66ba813-2cff-4e6b-ae7f-cce1dcd8bd64",
  "filename": "three_year.pdf",
  "company_name": "Example Industries",
  "currency": "USD",
  "has_financial_data": true,
  "available_years": ["2023", "2024", "2025"],
  "kpi_cards": [
    {
      "label": "Total Revenue",
      "value": 1200000.0,
      "formatted_value": "$1.20M",
      "currency": "USD",
      "period": "FY2025",
      "yoy_change": 26.32,
      "yoy_change_formatted": "+26.32%",
      "source_citation": "Page 1"
    },
    {
      "label": "Gross Profit",
      "value": 420000.0,
      "formatted_value": "$420K",
      "currency": "USD",
      "period": "FY2025",
      "yoy_change": 31.25,
      "yoy_change_formatted": "+31.25%",
      "source_citation": "Page 1"
    },
    {
      "label": "Gross Margin",
      "value": 35.0,
      "formatted_value": "35.00%",
      "period": "FY2025",
      "yoy_change": 1.32,
      "yoy_change_formatted": "+1.32%",
      "source_citation": "Derived (1)"
    },
    {
      "label": "Net Income",
      "value": 91000.0,
      "formatted_value": "$91K",
      "currency": "USD",
      "period": "FY2025",
      "yoy_change": 16.67,
      "yoy_change_formatted": "+16.67%",
      "source_citation": "Page 1"
    }
  ],
  "revenue_trend": [
    { "period": "2023", "fiscal_year": "FY2023", "revenue": 820000.0, "formatted": "$820K", "currency": "USD" },
    { "period": "2024", "fiscal_year": "FY2024", "revenue": 950000.0, "formatted": "$950K", "currency": "USD" },
    { "period": "2025", "fiscal_year": "FY2025", "revenue": 1200000.0, "formatted": "$1.20M", "currency": "USD" }
  ],
  "margin_trend": [
    { "period": "2023", "fiscal_year": "FY2023", "gross_profit_margin": 31.71, "net_profit_margin": 7.93 },
    { "period": "2024", "fiscal_year": "FY2024", "gross_profit_margin": 33.68, "net_profit_margin": 8.21 },
    { "period": "2025", "fiscal_year": "FY2025", "gross_profit_margin": 35.0, "net_profit_margin": 7.58 }
  ],
  "summary": {
    "revenue_performance": "Total revenue increased from $820K in FY2023 to $1.20M in FY2025 (+46.34% cumulative) with a year-over-year growth rate of +26.32% in FY2025.",
    "profitability": "In FY2025, Gross profit reached $420K (35.00% gross margin); net income was $91K (7.58% net profit margin).",
    "growth": "Year-over-year operational expansion: FY2024 revenue grew +15.85%; gross profit shifted +23.08%; net income shifted +20.00%; FY2025 revenue grew +26.32%; gross profit shifted +31.25%; net income shifted +16.67%.",
    "key_observations": [
      "Gross profit margin expanded steadily across reporting years (31.71% in FY2023 → 33.68% in FY2024 → 35.00% in FY2025), demonstrating improved operational unit economics."
    ],
    "citations": ["[Source 1] Page 1: Consolidated Income Statement"]
  }
}
```

### Web Application Navigation

The frontend client provides three primary views with top-level navigation:
- `/dashboard` — **Financial Analytics Dashboard**: Select any completed document to view instant KPI cards, interactive SVG trend charts, and table-grounded AI summaries.
- `/documents` — **Document Library**: Upload, monitor indexing status, and manage private financial PDFs.
- `/chat` — **AI Assistant**: Converse with the evidence-aware RAG pipeline with interactive Markdown tables, verifiable source citations, and confidence badges.

An empty `document_ids` array searches all completed, indexed documents owned by the current user. Pass the returned `session_id` on a later request to append a follow-up to the same saved conversation.

```json
{
  "session_id": "46e23573-6a73-45e5-aa0a-7468daef13ba",
  "answer": "FY2025 revenue was $1,250.50 [Source 1].",
  "sources": [{
    "document_id": "5cd36ea1-2bc1-4527-999e-c6f159d777e3",
    "filename": "annual-report.pdf",
    "page_numbers": [42],
    "excerpt": "FY2025 Revenue was $1,250.50...",
    "chunk_id": "f501f204-04d6-5a95-85b0-119dc8ad6508",
    "similarity_score": 0.87321
  }],
  "retrieved_chunks_count": 1,
  "model_name": "gpt-4.1-mini",
  "retrieval_time_ms": 18.4,
  "generation_time_ms": 814.2,
  "usage": {"input_tokens": 640, "output_tokens": 52, "total_tokens": 692, "estimated_cost_usd": null},
  "retrieval": {
    "selected_strategy": "hybrid",
    "selection_reason": "The query compares financial values, periods, or conditions and benefits from exact and contextual retrieval.",
    "query_analysis": {"query_type": "comparison", "has_financial_year": true, "has_comparison": true},
    "keyword_result_count": 5,
    "semantic_result_count": 5,
    "fusion_result_count": 5,
    "retrieved_chunks_count": 5,
    "retrieval_time_ms": 25.4
  },
  "verification": {
    "evidence_status": "sufficient",
    "overall_status": "verified",
    "relevance_score": 1.0,
    "sufficiency_score": 1.0,
    "supported_aspects": ["2025 revenue"],
    "missing_aspects": [],
    "claims_checked": 1,
    "supported_claims": 1,
    "unsupported_claims": 0,
    "supporting_citations": 1,
    "retrieval_attempts": 1,
    "revision_attempts": 0
  },
  "confidence": {
    "level": "high",
    "score": 1.0,
    "factors": {
      "retrieval_relevance": 1.0,
      "evidence_sufficiency": 1.0,
      "claim_support": 1.0,
      "citation_validity": 1.0
    },
    "calibrated_probability": false,
    "explanation": "A deterministic evidence-quality score, not a calibrated probability of factual truth."
  }
}
```

Insufficient evidence returns no sources and does not call the configured LLM:

```json
{
  "answer": "I could not find sufficient evidence in the uploaded documents to answer this question.",
  "sources": [],
  "verification": {
    "evidence_status": "insufficient",
    "overall_status": "abstained",
    "missing_aspects": ["2025 net profit"],
    "claims_checked": 0,
    "retrieval_attempts": 1
  },
  "confidence": {
    "level": "low",
    "calibrated_probability": false
  }
}
```

## Migrations

Run these commands from `backend/` with `DATABASE_URL` pointing at the intended database:

```powershell
alembic current
alembic upgrade head
alembic downgrade -1
alembic history
```

Create future migrations only after reviewing model changes:

```powershell
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Migration `20261103_0003` adds indexing metadata and structured chat-source fields. Migration `20261103_0004` adds retrieval diagnostics. Migration `20261103_0005` adds nullable evidence status, verification status, confidence score, verification/confidence JSON, and retrieval-attempt fields. Older messages remain readable because every Phase 6 field is nullable. Documents completed before Phase 4 are marked `failed` with a retry message so their existing relational chunks can be indexed safely.

## Environment and API keys

The local embedding model, ChromaDB, and Ollama require no external LLM API key.

The Sentence Transformers embedding model downloads model weights on first use in Phase 4. Production deployments should cache the approved model artifact and pin its revision.

Never commit `.env`, uploaded documents, database volumes, model credentials, or production JWT secrets.

Authentication variables include `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `AUTH_COOKIE_NAME`, `CSRF_COOKIE_NAME`, `COOKIE_SECURE`, and `COOKIE_SAMESITE`. Startup rejects placeholder JWT secrets in staging or production and rejects `SameSite=None` cookies without the Secure flag.

Document variables:

- `UPLOAD_DIR` — private backend storage root; never point it at frontend `public/` or another web-served directory.
- `MAX_UPLOAD_SIZE_MB` — server-enforced streaming upload limit.
- `UPLOAD_READ_CHUNK_BYTES` — upload streaming buffer size.
- `CHUNK_SIZE_TOKENS` — approximate target chunk size; default 500.
- `CHUNK_OVERLAP_TOKENS` — approximate overlap; default 100 and must be smaller than the target.
- `VITE_MAX_UPLOAD_SIZE_MB` — matching browser-side early validation limit; the backend remains authoritative.

Semantic RAG variables:

- `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_QUERY_PREFIX`.
- `CHROMA_COLLECTION` — persistent collection name; default `financial_document_chunks`.
- `RAG_TOP_K`, `RAG_MIN_SIMILARITY`, `RAG_SOURCE_EXCERPT_CHARS`.
- `LLM_PROVIDER` — `ollama` only.
- `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`.
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_CONNECT_TIMEOUT_SECONDS`.

For the Windows-host Ollama setup used with Docker Desktop, select `ollama`, use
`http://host.docker.internal:11434`, and use the lightweight `qwen2.5:7b` model.
Ollama replaces only answer generation; BGE embeddings, BM25/semantic retrieval,
ChromaDB, evidence verification, claim checking, citations, and abstention remain
unchanged. See [Environment configuration](docs/ENVIRONMENT_CONFIGURATION.md#local-ollama-on-windows-with-docker-desktop)
for installation, switching, networking, and troubleshooting commands.

Adaptive retrieval variables:

- `BM25_K1`, `BM25_B`, `BM25_EPSILON` — keyword-ranking parameters.
- `BM25_CACHE_USERS` — maximum in-process per-user BM25 indexes retained by each backend worker.
- `RRF_CONSTANT` — rank-fusion constant; default 60.
- `ADAPTIVE_EXACT_TERM_THRESHOLD` — exact-signal count that can trigger keyword routing; default 1.

Evidence and claim verification variables:

- `EVIDENCE_RELEVANCE_THRESHOLD`, `EVIDENCE_SUFFICIENCY_THRESHOLD`, `EVIDENCE_WEAK_THRESHOLD`.
- `EVIDENCE_MAX_TOP_K` — upper bound for retrieve-more expansion; default 15.
- `EVIDENCE_MAX_RETRIEVAL_ATTEMPTS` — maximum additional retrieval calls; default 2.
- `ANSWER_MAX_REVISION_ATTEMPTS` — bounded deterministic answer revision; default 1.
- `CLAIM_SUPPORT_THRESHOLD` — minimum deterministic claim/evidence support score.

## Tests

The default suite uses an isolated in-memory SQLite database and never touches development data. To validate against PostgreSQL, create a dedicated database whose URL contains `test`, then set `TEST_DATABASE_URL`; the suite creates and drops its tables.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -q
python -m ruff check app alembic tests
```

Migration tests independently upgrade a temporary database to `head`, inspect its schema, and downgrade to `base`.

Tests generate synthetic PDFs in temporary directories and use deterministic embedding/vector/LLM doubles by default. Coverage includes all prior-phase behavior plus requirement analysis, sufficient/weak/insufficient decisions, reporting-period and metric coverage, bounded retrieve-more, deduplication, ownership rejection, claim-level numerical and period checks, invalid citations, safe revision, abstention, confidence factors, persistence, and the complete upload-to-verified-answer API workflow. Opt-in real-service tests use `RUN_CHROMA_INTEGRATION=1` and `RUN_OLLAMA_INTEGRATION=1`.

Historical Phase 6 verification completed with **92 passed, 2 skipped**. The current bounded Phase 7.5 run collected 110 tests and completed **53 passed, 0 failed, 1 skipped, 55 deselected**, with the migration test separately not run because of the documented managed-Windows stall. See the Phase 7.5 verification report for the exact scope; neither run proves live PostgreSQL, ChromaDB, or provider behavior.

## Retrieval evaluation

Run the reproducible benchmark from `backend/`:

```powershell
python -m app.evaluation.runner
```

This writes machine-readable `app/evaluation/results.json` and `app/evaluation/report.md`. The 2026-11-03 run used the real configured `BAAI/bge-small-en-v1.5` model, ten synthetic chunks, eight labelled questions, and `top_k=3`. Model loading and document indexing are excluded from query latency.

| Experiment | Precision@3 | Recall@3 | MRR | nDCG@3 | Avg retrieval latency |
|---|---:|---:|---:|---:|---:|
| A — Semantic only | 0.3750 | 1.0000 | 1.0000 | 1.0000 | 23.170 ms |
| B — Hybrid for all | 0.3750 | 1.0000 | 0.9167 | 0.9375 | 22.995 ms |
| C — Adaptive | 0.3750 | 1.0000 | 1.0000 | 1.0000 | 14.773 ms |

Adaptive strategy-selection accuracy was 100% against the eight manual route labels. These results validate the harness and show that always-on hybrid retrieval can hurt conceptual queries in this small fixture; they are not statistically sufficient to claim general product improvement.

### Evidence and claim evaluation

```powershell
python -m app.evaluation.evidence_runner
```

This writes `app/evaluation/evidence_results.json` and `app/evaluation/evidence_report.md`. Eight synthetic labelled cases compare Phase 5-style ungated answers, evidence gating, and evidence plus claim verification.

| Experiment | Evidence P/R | Claim P/R | Unsupported claim rate | Abstention P/R | Citation correctness | Answer correctness | Extra retrieval | Verify latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A — No verification | 0.625/1.000 | 0.667/1.000 | 0.500 | 0.000/0.000 | 0.600 | 0.375 | 0.000 | 0.000 ms |
| B — Evidence check | 1.000/1.000 | 0.667/1.000 | 0.333 | 1.000/1.000 | 0.833 | 0.750 | 0.375 | 0.642 ms |
| C — Evidence + claims | 1.000/1.000 | 1.000/1.000 | 0.000 | 0.600/1.000 | 1.000 | 0.750 | 0.375 | 0.443 ms |

Claim verification removed all unsupported returned claims in this fixture, but it also abstained on two answerable cases whose fixed candidate answers contained a wrong value or citation. That tradeoff explains the 0.600 abstention precision and why answer correctness did not improve from experiment B to C. Candidate answers are versioned fixtures, so no provider was called and LLM cost is recorded as unavailable rather than invented.

## Delivery status and next milestones

1. **Foundation (complete):** monorepo, configuration, logging, React shell, FastAPI health API, PostgreSQL, ChromaDB, Docker, smoke tests.
2. **Authentication (complete):** SQLAlchemy models and migrations, registration/login/me/logout APIs, Argon2 hashing, expiring JWTs, HttpOnly cookie sessions, CSRF protection, and protected frontend routes.
3. **Document management (complete):** secure PDF upload, ownership checks, PyMuPDF extraction, page-aware cleaning/chunking, status tracking, retry/deletion, and document UI.
4. **Basic semantic RAG (complete):** BGE Sentence Transformers embeddings, persistent Chroma collection, semantic retrieval, Ollama adapter, grounded answers, structured citations, chat persistence, and responsive chat UI.
5. **Adaptive hybrid retrieval (complete):** cached per-user BM25, transparent query rules, semantic/keyword/hybrid modes, RRF, persisted diagnostics, frontend telemetry, and measured retrieval evaluation.
6. **Evidence verification (complete):** structured requirements, relevance and sufficiency checks, bounded retrieve-more, claim/citation validation, safe revision, explainable evidence confidence, persisted diagnostics, and measured evaluation.
7. **Real-report, reliability, and product validation (complete for documented scope):** 16-case official-report evaluation, environment-limited application checks, CPU performance observations, PDF reliability, UI/accessibility polish, secure production configuration, and release documentation.
8. **Staging acceptance (blocked):** live PostgreSQL and ChromaDB, HTTPS cookies/CSRF/CORS, authorized provider generation, full two-user browser E2E, backup restoration, and operational telemetry.
9. **Future enhancements:** unit-aware financial calculations, OCR, background workers, authenticated PDF viewing, shared keyword-index invalidation, larger human-labelled evaluation, and calibrated thresholds.

## Dependency plan

Current runtime dependencies are declared in `backend/requirements.txt` and `frontend/package.json`:

- Already implemented: `alembic`, `pwdlib[argon2]`, `PyJWT`, `PyMuPDF`, `sentence-transformers`, `rank-bm25`, and the Chroma HTTP client. Provider calls reuse `httpx`.
- Current testing: `pytest`, `pytest-asyncio`, and `pytest-cov`; evaluation adapters and scripts arrive with their corresponding phases.

Keeping future dependencies out of the current build makes installation smaller and ensures every added package accompanies an implemented, tested feature.

## Current limitations

- Processing is synchronous. The status API and frontend refresh control are ready for a background worker, but no task queue is configured yet.
- Text extraction does not perform OCR; scanned image-only pages are retained as empty pages.
- Chunk token counts use a deterministic approximation rather than a model-specific tokenizer.
- Indexing and answer generation run synchronously in API requests; production scale should move indexing to a worker queue.
- Query routing uses explainable heuristics rather than a trained classifier and currently analyzes only the latest question.
- BM25 caches are process-local; a multi-worker production deployment should use shared invalidation or a versioned external index.
- The evaluation corpus remains small. Phase 7.1 adds two official reports and 16 labelled questions, but it is still insufficient for a general research or production-accuracy claim.
- Evidence and entailment checks are deterministic heuristics; paraphrases, complex tables, and multi-step reasoning can produce false positives or conservative false abstentions.
- The confidence score is not calibrated and must not be interpreted as the probability that an answer is true.
- Claim revision removes unsupported sentences but does not ask the provider to rewrite prose; this avoids an extra model call but can make a partially retained answer less fluent.
- Synthetic evidence fixtures use fixed candidate answers; the real-report evaluation disables LLM generation. Production answer-quality claims require a larger human-labelled corpus, authorized provider runs, and calibrated thresholds.
- Follow-up messages are saved in a session, but retrieval currently embeds the latest question without conversational query rewriting.
- A final filesystem unlink failure can leave an already quarantined file for an operator cleanup pass; database records are still removed without exposing the file publicly.
- Live PostgreSQL, ChromaDB, TLS/reverse proxy, backup restoration, provider generation, and production load behavior have not passed staging acceptance.
- The current `main` branch has no commits and all eligible source files are untracked; follow the release-baseline guide before producing a release.

## Repository structure

```text
FinAssist AI/
|-- .env.example
|-- .gitignore
|-- docker-compose.yml
|-- README.md
|-- backend/
|   |-- app/
|   |   |-- main.py
|   |   |-- config.py
|   |   |-- database.py
|   |   |-- models/          # User, document, and chat models
|   |   |-- schemas/         # Pydantic request/response schemas
|   |   |-- routers/         # Health, auth, documents, and semantic chat APIs
|   |   |-- services/        # Retrieval, evidence, claims, confidence, LLM, RAG
|   |   |-- evaluation/      # Labelled benchmark, metrics, runner, actual results
|   |   `-- utils/           # Security and shared helpers
|   |-- tests/
|   |-- uploads/
|   |-- Dockerfile
|   |-- requirements.txt
|   `-- requirements-dev.txt
|-- frontend/
|   |-- src/
|   |   |-- components/      # Shared UI and feature components (Phase 2+)
|   |   |-- context/         # Cookie-backed authentication state
|   |   |-- lib/api.js
|   |   |-- pages/
|   |   |-- App.jsx
|   |   |-- index.css
|   |   `-- main.jsx
|   |-- Dockerfile
|   |-- nginx.conf
|   |-- package.json
|   `-- vite.config.js
`-- docs/                    # Architecture, API, deployment, screenshots
```

## Deployment direction

The production target is a static frontend on a CDN-backed host, a containerized FastAPI service, managed PostgreSQL, private persistent ChromaDB, and private object storage for uploaded PDFs. Public exposure of ChromaDB is not recommended; network access should be limited to the backend service.

