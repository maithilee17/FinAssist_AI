# Phase 3A baseline (before application edits)

Working tree: all project files are untracked; `main` has no commits. Branch creation was denied by the filesystem (`.git/HEAD.lock`); no files were staged/reset or overwritten to establish a branch.

Phase 2 audit: executive summary states 54 executed / 52 passed / 2 partial; final category table adds up to 64 / 62 / 2. Detailed QA tables contain 36 PDF rows and 14 XDOC rows. The remaining reported 14 are 4 ingestion, 6 baseline and 4 persistence checks. No corresponding Phase 2 machine-readable request/response run was found beside the report. These are reported observations, not independently rerun live passes. In particular XDOC-04 asks for growth but its quoted answer only states the two revenues; the PASS label alone is not evidence of complete answer coverage. Phase 2 also says React 18 while current package.json declares React 19.

Executed before changes: `python -m pytest tests -m "not anyio and not asyncio" --ignore=tests/test_migrations.py -q`: **233 passed, 2 skipped, 93 deselected, 4.63 s**. Async/migration cases are excluded because this environment previously blocks asyncio socket-pair initialization. Full-suite execution is attempted separately with a bound. This baseline is unit/offline verification, not live integration.

The companion phase3a_baseline.json contains fixed-fixture issue reproductions, source hashes and comparable offline planning timings. Its timings exclude BM25, BGE, Chroma and Ollama and cannot establish live retrieval latency or answer accuracy. Fixtures reproduce text layouts described in Phase 2; they are not claimed live passage captures.
