# Embedding and Indexing Diagnostics

The public `BAAI/bge-small-en-v1.5` model does not require a Hugging Face token. An unauthenticated warning can indicate lower download rate limits, but it is not proof of an embedding failure.

## What the repaired pipeline validates

- The configured model loads on the configured device.
- The model reports the configured dimension (`384` by default).
- Every non-empty chunk produces exactly one vector.
- Every vector has the same dimension, contains only finite values, has non-zero magnitude, and is normalized.
- ChromaDB receives one vector per stable chunk ID and the stored count is verified before the document becomes `completed`/Indexed.
- A partial vector-store failure triggers a cleanup attempt. Relational pages/chunks and the private PDF remain available for retry.
- Backend logs retain the full exception chain without logging chunk text; the document record receives a safe diagnostic code and actionable message.

## Run the diagnostic

From the repository root, after the operator has started the backend service:

```powershell
# Allow a missing public model to download into the persistent cache.
docker compose exec backend python -m app.diagnostics.embedding

# After the first successful download, prove the cache is complete and usable offline.
docker compose exec backend python -m app.diagnostics.embedding --local-files-only
```

The successful result reports the Python, Torch, Sentence Transformers, model, device, expected/actual dimension, document/query vector counts, cache writability, and finite-vector status. It does not print embeddings, prompts, PDF text, tokens, or credentials.

For a direct non-container environment:

```powershell
cd backend
$env:HF_HOME = (Resolve-Path .model-cache).Path
.\.venv\Scripts\python.exe -m app.diagnostics.embedding
```

## Diagnostic codes

| Code | Meaning | Recovery |
| --- | --- | --- |
| `model_load_failed` | Model import/download/cache initialization failed | Check backend traceback, cache writability, network/TLS, and CPU package installation |
| `model_dimension_mismatch` | Loaded model does not match `EMBEDDING_EXPECTED_DIMENSION` | Correct the model/dimension configuration; do not reuse an incompatible Chroma collection |
| `document_inference_failed` | Torch inference failed | Check memory, lower `EMBEDDING_BATCH_SIZE`, and verify cache integrity |
| `embedding_count_mismatch` | Model returned a different number of vectors | Treat as an incompatible/broken runtime; do not index |
| `embedding_dimension_mismatch` | Batch vectors have inconsistent dimensions | Treat as invalid model output; do not index |
| `non_finite_embedding` / `empty_embedding` / `unnormalized_embedding` | Invalid numeric output | Treat as invalid model/runtime output; do not index |
| `vector_store` stage | Chroma open/upsert/count failed | Check `/api/health/ready`, collection dimension, network, and Chroma logs |

## Cache and permissions

The backend image runs application code as the non-root `finassist` user. Its entrypoint repairs ownership of `/app/model-cache` and `/app/uploads`, including existing named volumes, then drops root privileges. It does not delete cached models or uploaded PDFs.

If a download was interrupted, rerun the online diagnostic to let Hugging Face complete missing files. Do not delete PostgreSQL, ChromaDB, or upload volumes. If an operator decides the model cache alone is corrupt, back it up before any manual cache repair and keep application data volumes untouched.

`EMBEDDING_LOCAL_FILES_ONLY=true` is appropriate only after the diagnostic succeeds with `--local-files-only`. A missing cache in that mode must fail clearly instead of silently using fake vectors.

## Collection compatibility

`BAAI/bge-small-en-v1.5` produces 384-dimensional vectors. ChromaDB fixes collection dimensionality on the first insert and rejects a different dimension later. If the embedding model changes, use a new versioned collection name and reindex from PostgreSQL chunks; do not mix dimensions in one collection.

## Safe retry

The document page provides Retry for failed records. Retry reuses the private PDF and relational chunks when available, deletes prior vectors by authenticated user/document filter, upserts stable IDs, verifies the exact count, and marks the document Indexed only after all steps succeed.
