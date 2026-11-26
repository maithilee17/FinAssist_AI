# Operations, Observability, Backup, and Restore

## Observability principles

Measure each pipeline stage independently. Use bounded-cardinality labels such as route, status, retrieval strategy, evidence status, provider/model alias, and error class. Do not label metrics with user IDs, document IDs, filenames, questions, excerpts, emails, tokens, or filesystem paths.

## Recommended metrics

| Metric | Suggested type | Purpose |
| --- | --- | --- |
| `finassist_http_request_duration_seconds` | Histogram | API p50/p95/p99 by route template, method, and status |
| `finassist_http_requests_total` | Counter | Traffic, client errors, server errors, and rate-limit outcomes |
| `finassist_pdf_extraction_seconds` | Histogram | Page extraction latency by safe size/page buckets |
| `finassist_pdf_pages_total` | Counter | Processed and empty pages without document labels |
| `finassist_chunking_seconds` / `chunks_total` | Histogram/counter | Chunking latency and throughput |
| `finassist_embedding_seconds` / `embeddings_total` | Histogram/counter | Batch latency and throughput by model/device alias |
| `finassist_indexing_seconds` | Histogram | Vector upsert and count-verification latency |
| `finassist_retrieval_seconds` | Histogram | Keyword, semantic, and hybrid retrieval latency |
| `finassist_verification_seconds` | Histogram | Evidence and claim verification latency separately |
| `finassist_llm_generation_seconds` | Histogram | Provider generation latency when explicitly enabled |
| `finassist_questions_total` | Counter | Outcomes by answered/abstained/error and evidence status |
| `finassist_retrieval_attempts` | Histogram | Retrieve-more frequency and bounded-attempt behavior |
| `finassist_processing_failures_total` | Counter | Safe error class and processing stage |
| `finassist_process_resident_memory_bytes` | Gauge | Worker memory pressure |
| `finassist_storage_bytes` | Gauge | Private PDF, vector, database, and model-cache growth |

Track LLM token usage and estimated cost only when the provider returns usage. Never estimate missing cost as an observed value.

## Logs and traces

- Generate or propagate a request correlation ID and include route template, status, duration, safe error category, and selected retrieval strategy.
- Use structured logs in staging/production. Redact `Authorization`, `Cookie`, `Set-Cookie`, CSRF values, passwords, API keys, database URLs, filenames when sensitive, private paths, questions, excerpts, and model prompts.
- Record document and session identifiers only after a privacy review; hashed or short-lived correlation aliases are preferable.
- Trace extraction, embedding, indexing, retrieval, verification, and generation as separate spans. Disable prompt/body capture by default.
- Alert on readiness failures, persistent indexing failures, high abstention shifts, provider timeouts, 5xx rate, memory pressure, storage capacity, and backup failures.

## Historical measurements—not staging SLOs

Phase 7.1 used two official reports, 662 chunks, and 16 labelled questions on CPU with cached production BGE vectors. It measured mean retrieval latency of **639.044 ms**, mean verification latency of **27.509 ms**, and mean pipeline latency without an LLM of **668.170 ms**. Citation-page correctness on answerable cases was **0.700** and fully supported reference claims were **0.600**. The corpus is small; these are evaluation observations, not general production guarantees.

Phase 7.3 observed NVIDIA extraction at **813.189 ms baseline vs 669.296 ms optimized** and peak working-set growth at **106,921,984 vs 56,770,560 bytes** in single runs. It also measured evaluation-only exact in-memory cosine search at **11.377 ms vs 0.862 ms** over 16 probes with identical top-5 rankings. That cosine result is not a ChromaDB benchmark, and the single extraction runs are not statistically significant.

No new staging end-to-end latency, live ChromaDB latency, provider latency/cost, or GPU measurement was produced in Phase 7.5.

## Backup policy

Back up four coordinated domains:

1. PostgreSQL relational data and Alembic revision.
2. Private uploaded PDFs and quarantine state.
3. ChromaDB persistent data or a documented rebuild-from-relational-chunks procedure.
4. Runtime configuration metadata excluding secrets; secrets stay in the secret manager and follow its own recovery process.

Use encrypted storage, least-privilege backup identities, retention appropriate to user deletion/privacy requirements, immutable copies where justified, and monitored backup jobs. A successful job is not proof of recoverability.

## Restore rehearsal

1. Select a known backup and record its timestamp, application commit, migration revision, embedding model, and collection name.
2. Restore into an isolated environment with no production traffic or provider credentials.
3. Restore PostgreSQL and confirm the recorded Alembic revision before applying any newer migration.
4. Restore private PDFs with ownership and restrictive permissions.
5. Restore ChromaDB or rebuild vectors from relational chunks using the recorded embedding model.
6. Verify counts across documents, pages, chunks, indexed vectors, sessions, and messages.
7. Run two-user isolation, retrieval/citation, deletion, and abstention smoke tests.
8. Record recovery time, recovery point, mismatches, remediation, and sign-off.

Never test a destructive restore against production. Commands depend on the operator's managed PostgreSQL/Chroma/storage platform and therefore are intentionally not hard-coded here.
