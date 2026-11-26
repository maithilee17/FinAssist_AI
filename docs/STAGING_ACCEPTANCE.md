# Staging Acceptance Checklist

Use this checklist only after the operator has started and secured the required services. Record the date, commit SHA, environment name, tester, and evidence link for every run. Never paste credentials, cookies, document text, or authorization headers into the report.

## Status categories

- **Locally verified:** covered by deterministic/unit checks in Phases 7.1–7.4.
- **Manual infrastructure:** requires staging PostgreSQL, ChromaDB, storage, TLS, or a browser.
- **External credentials:** requires an explicitly approved LLM provider configuration.
- **Not yet tested:** no passing evidence exists yet.

## Gate 1 — Release identity and configuration

- [ ] Record the reviewed Git commit SHA and confirm `git status --short` is empty.
- [ ] Build from that SHA; do not deploy an untracked working directory.
- [ ] Supply secrets through the platform secret manager, not `.env` committed to Git.
- [ ] Set `APP_ENV=staging` or `production`, a unique 32+ character `JWT_SECRET_KEY`, and `COOKIE_SECURE=true`.
- [ ] Set exact HTTPS `CORS_ORIGINS` and a matching public `VITE_API_URL`.
- [ ] Confirm the private upload path is persistent, writable by only the backend identity, and outside the web root.
- [ ] Confirm `/api/health/live` returns 200 and `/api/health/ready` remains 503 until both data services are healthy.

## Gate 2 — PostgreSQL and migrations

Status: **manual infrastructure**.

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

- [ ] The connection uses the staging PostgreSQL URL, not SQLite and not a production database.
- [ ] `alembic current` reports `20261103_0005 (head)` after upgrade.
- [ ] Registration creates a user whose password column contains an Argon2 hash, never plaintext.
- [ ] Foreign keys and ownership indexes exist for documents, pages, chunks, sessions, and messages.
- [ ] Upgrade is tested on a restored staging backup before production rollout.
- [ ] Downgrade is rehearsed only on disposable/staging data and any destructive migration is explicitly reviewed.

## Gate 3 — ChromaDB

Status: **manual infrastructure**.

- [ ] Application readiness reports ChromaDB healthy.
- [ ] Uploading a report reaches `completed` only after the expected vector count is stored.
- [ ] A query for User A returns only metadata with User A's ID.
- [ ] Selected-document filtering excludes other owned documents when requested.
- [ ] User B cannot retrieve User A's chunk IDs even when IDs are known.
- [ ] Retrying indexing uses stable IDs and does not create duplicates.
- [ ] Deleting a document removes its vectors and does not affect another document or user.
- [ ] ChromaDB is reachable only from trusted backend/network identities.

## Gate 4 — HTTPS authentication, cookies, CSRF, and CORS

Status: **manual infrastructure/browser**.

- [ ] Registration, valid login, generic invalid login, `/api/auth/me`, reload persistence, and logout work over HTTPS.
- [ ] The auth cookie is `HttpOnly`, `Secure`, has the intended `SameSite` policy, and is scoped narrowly.
- [ ] A state-changing cookie request without the matching CSRF header is rejected.
- [ ] A request from an unlisted origin receives no credentialed CORS permission.
- [ ] The configured frontend origin succeeds with credentials.
- [ ] Expired, malformed, and wrong-signature JWTs receive 401 without sensitive detail.
- [ ] User A receives 404—not existence disclosure—for User B's document/session identifiers.

## Gate 5 — Complete document lifecycle

Status: **manual infrastructure**.

- [ ] Upload an authorized, checksum-recorded financial PDF.
- [ ] Confirm private file existence, metadata, size, page count, extracted page count, chunk count, and one-based page references.
- [ ] Confirm financial figures preserve currency, commas, decimals, percentages, parentheses/negative values, units, and reporting periods.
- [ ] Confirm processing moves through uploaded, processing, indexing, and completed.
- [ ] Corrupted, encrypted, oversized, non-PDF, empty-text, and path-traversal attempts fail safely.
- [ ] Retry a controlled indexing failure without re-uploading.
- [ ] Delete the document and verify relational rows, private file, and vector records independently.

## Gate 6 — RAG and answer policy

Status: retrieval requires infrastructure; generation requires **explicitly authorized external credentials** or an approved local provider.

- [ ] Exact-value question selects keyword or hybrid retrieval and preserves value, unit, currency, and period.
- [ ] Conceptual question retrieves semantically relevant passages.
- [ ] Comparison question covers both periods and consistent units.
- [ ] Multi-passage question retrieves all required aspects.
- [ ] Unanswerable question abstains without inventing a value.
- [ ] Each citation maps to an actual returned chunk, document, and one-based page.
- [ ] Unsupported material claims are removed, marked unsupported, or cause abstention.
- [ ] Confidence is described as evidence quality, not calibrated factual probability.
- [ ] Record provider model, latency, usage, and cost metadata where available without logging prompts or document content.

## Gate 7 — Two-user isolation

Status: **manual infrastructure/browser**.

- [ ] Use two independently registered accounts and separate browser contexts.
- [ ] User A cannot list, fetch, poll, retry, delete, retrieve, cite, or chat with User B's documents.
- [ ] User A cannot fetch or delete User B's chat sessions.
- [ ] Deleting User A's data leaves User B's relational rows, files, vectors, and history unchanged.

## Gate 8 — Operational acceptance

- [ ] Logs include request correlation and safe timing/status fields but no credentials, cookies, full passages, private paths, or secrets.
- [ ] Alerts distinguish liveness, readiness, indexing failures, provider failures, and storage exhaustion.
- [ ] PostgreSQL, vector data, PDFs, and configuration backups have documented retention and encryption.
- [ ] Restore a backup into an isolated environment and verify relational/vector/document consistency.
- [ ] Reindex procedure, JWT rotation, provider outage, and quarantined-file cleanup are rehearsed.
- [ ] Sign-off records all failed, blocked, skipped, and accepted-risk items.

## Evidence already available

- Local deterministic/unit checks: [Phase 7.4 verification](PHASE_7_4_VERIFICATION.md).
- Real-report retrieval/verification: `backend/app/evaluation/real_world/`.
- Environment-limited application run: `backend/app/evaluation/end_to_end/`.
- CPU performance/reliability: `backend/app/evaluation/performance/`.

None of those artifacts replaces staging PostgreSQL, live ChromaDB, HTTPS, or authorized provider acceptance.
