# Phase 7.3 Reproducibility

## Environment

- Windows, Python 3.11 virtual environment in `backend/.venv`.
- CPU-only BGE execution.
- Existing Phase 7.1 PDFs, chunk caches, and embedding caches.
- No Docker operations.
- No PostgreSQL, live ChromaDB, Ollama, OpenAI, or other paid LLM call.

Run commands from the repository root unless a command changes directory explicitly.

## Preserve the saved measurements

The checked-in baseline and optimized artifacts are the source of the reported numbers. Their SHA-256 values are:

```text
aa6b2eed71c3cbde59151f7b7dffad32955a3999761a2a938c030384095abd9a  baseline_results.json
66254fdac810c6a8bffbe97d7ab0759a219e8f39977d0d4c4a901e16df3d4719  optimized_results.json
f6cf250d574cb33944de50657ea56b5549795dcf70797888b3b171456222b46a  ../real_world/results.json
```

Verify them without rerunning benchmarks:

```powershell
Get-FileHash backend/app/evaluation/performance/baseline_results.json -Algorithm SHA256
Get-FileHash backend/app/evaluation/performance/optimized_results.json -Algorithm SHA256
Get-FileHash backend/app/evaluation/real_world/results.json -Algorithm SHA256
```

## Benchmark commands

These commands overwrite their corresponding result artifact. Copy or rename the existing file first if historical measurements must be retained.

Baseline, using the original Python-loop exact-cosine substitute and cached BGE vectors:

```powershell
Set-Location backend
& .venv/Scripts/python.exe -u -m app.evaluation.performance.runner --label baseline --skip-query-inference --trust-phase71-checksums
```

Optimized, using path-backed PDF opening and vectorized exact cosine:

```powershell
Set-Location backend
& .venv/Scripts/python.exe -u -m app.evaluation.performance.runner --label optimized --skip-query-inference --trust-phase71-checksums --vectorized
```

Do not add `--execute-embeddings` for the reported run. Fresh full-corpus BGE generation did not complete on this CPU host and no throughput value was accepted.

The runner verifies cached chunk fingerprints, embedding IDs, source file byte sizes, and ranking outputs. `--trust-phase71-checksums` reuses the already validated Phase 7.1 source checksums; omit it to rehash the PDFs.

## Regression checks

Focused PDF and chunk tests:

```powershell
Set-Location backend
& .venv/Scripts/python.exe -m pytest tests/test_pdf_processing.py tests/test_chunking.py -q
```

Synchronous backend subset used in this environment:

```powershell
Set-Location backend
& .venv/Scripts/python.exe -m pytest -m "not anyio" --ignore tests/test_migrations.py -q
```

Full backend suite (expected to be attempted in an unrestricted local shell):

```powershell
Set-Location backend
& .venv/Scripts/python.exe -m pytest -q
```

Phase 7.1 artifact and metric checks:

```powershell
Set-Location backend
& .venv/Scripts/python.exe -m pytest tests/test_evaluation_metrics.py tests/test_evidence_evaluation.py -q
```

Static and frontend checks:

```powershell
Set-Location backend
& .venv/Scripts/ruff.exe check .
Set-Location ../frontend
npm run lint
npm run build
```

## Blocked integrations

- PostgreSQL: not started or tested.
- ChromaDB: not started or tested; in-memory exact cosine is explicitly a substitute.
- LLM: not configured or called.
- Docker: prohibited and not used.
- GPU: unavailable.
- OCR: not implemented.

The managed Windows sandbox stalled in event-loop `socketpair()` creation and in the migration test. Run the full backend suite in the developer's normal environment to resolve the 55 blocked/not-run outcomes.
