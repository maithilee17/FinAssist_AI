# FinAssist AI Phase 7.3 Performance and Reliability Report

## Status

Phase 7.3 production changes and the saved benchmark artifacts were verified. The result is **verified with environment blockers**, not an unrestricted full-suite pass: the managed Windows environment stalled when creating an asyncio event loop and during the migration test. Docker, PostgreSQL, ChromaDB, Ollama, and paid LLM APIs were not used.

## Workload and method

- Official NVIDIA FY2025 and Coca-Cola 2024 reports from Phase 7.1.
- 662 page-aware chunks and 384-dimensional normalized `BAAI/bge-small-en-v1.5` vectors.
- CPU execution only.
- Production PyMuPDF extraction, cleaning, chunking, BM25 construction/scoring, evidence verification, and claim verification.
- Semantic search math used an explicitly labelled in-memory exact-cosine substitute. It is not a ChromaDB benchmark.
- No LLM generation was enabled.

The baseline and optimized PDF figures are single-run observations. They are useful local measurements but do not establish statistical significance. The cosine values are averages across 16 fixed probes.

## Confirmed production optimization

`pdf_processor.py` previously loaded the complete PDF into a Python `bytes` object before opening it with PyMuPDF. It now reads only the first 1 KiB for header validation and lets PyMuPDF open the private server-side path directly. Validation failures close the PyMuPDF document, while normal inspection and extraction retain their existing `finally`-based close behavior.

Observed on the 49,970,589-byte NVIDIA report:

| Measurement | Baseline | Optimized | Observed change |
| --- | ---: | ---: | ---: |
| Extraction wall time | 813.189 ms | 669.296 ms | -17.695% |
| Peak working-set growth | 106,921,984 bytes | 56,770,560 bytes | -46.905% |

These are single runs. The Coca-Cola report measured 511.572 ms before and 598.526 ms after, demonstrating why no broad extraction-speed claim is made. The defensible result is reduced large-file memory growth, supported by the implementation change and regression test.

## Evaluation-harness optimization

The Phase 7.1 in-memory exact-cosine substitute used Python scalar loops. The performance runner adds NumPy matrix multiplication over the same cached normalized BGE vectors.

| Measurement | Baseline | Vectorized | Observed change |
| --- | ---: | ---: | ---: |
| Exact-cosine search average | 11.377 ms | 0.862 ms | -92.423% |

Top-5 chunk IDs were identical for all 16 probes. This optimization applies only to the local evaluation substitute. Live ChromaDB was unavailable and no ChromaDB performance claim is made.

## Other measured components

| Component | Baseline observation | Optimized-run observation | Interpretation |
| --- | ---: | ---: | --- |
| Cached embeddings load (662) | 14.371 ms | 15.081 ms | Normal run variance; no improvement claimed |
| BM25 cold build + score | 648.519 ms | 744.829 ms | No improvement claimed; database query excluded |
| BM25 warm score | 1.943 ms | 1.541 ms | No improvement claimed |
| Evidence verification | 13.504 ms | 12.960 ms | No improvement claimed |
| Claim verification | 2.831 ms | 2.629 ms | No improvement claimed |

The completed Phase 7.1 run remains the end-to-end no-LLM reference: 16 cases, 639.044 ms average retrieval, 27.509 ms average verification, and 668.170 ms average end-to-end latency. It used the evaluation cosine substitute, not live ChromaDB.

Fresh full-corpus BGE generation did not complete during the bounded CPU run, so embedding throughput and cold indexing latency are unavailable. Cached embeddings were not represented as fresh generation.

## PDF reliability

The performance runner completed seven checks successfully:

1. Corrupted PDF rejection.
2. Unsupported non-PDF content rejection.
3. Empty-text page preservation.
4. Financial punctuation preservation (`$1,234.56`, `-4.2%`, `FY2025`).
5. Multi-page order and one-based page references.
6. Retry after correcting a failed source.
7. Validation of the 49,970,589-byte, 181-page NVIDIA report.

The focused PDF and chunk regression suite passed 10/10. It includes Unicode financial values, page numbering, empty pages, invalid/corrupt/encrypted files, stable chunking, overlap, cross-document rejection, and a regression asserting the opener does not call `Path.read_bytes`. The latter test also deletes the file immediately after inspection, checking that Windows file handles are released.

OCR is not implemented. A valid image-only PDF can therefore have pages but no extractable text.

## Automated checks

- Backend collection: 103 tests.
- Unique outcomes obtained in bounded runs: 47 passed, 0 failed, 1 skipped, 55 blocked/not run.
- Synchronous subset excluding the blocked migration test: 46 passed, 1 skipped, 55 deselected.
- Full run: the first adaptive-routing test passed; the next async hybrid test stalled.
- Blocked tests identified:
  - `tests/test_adaptive_retrieval.py::test_hybrid_runs_both_systems_and_fuses_duplicate_chunk`
  - `tests/test_migrations.py::test_initial_migration_upgrade_and_downgrade`
- Phase 7.1 evaluation artifact/metric checks: 3 passed.
- Ruff: passed.
- Frontend ESLint: passed.
- Frontend Vite production build: passed; 1,759 modules transformed in 31.17 seconds.

No assertion failure was observed. The backend suite is not reported as fully passing because the current environment could not complete it. Phase 7.2's earlier full-suite result is not substituted for this run.

## Bottlenecks and limitations

- Cold CPU BGE generation is the dominant unresolved indexing cost, but this run did not produce a valid throughput value.
- The production semantic store and PostgreSQL query paths were unavailable. SQLite and in-memory cosine are not treated as equivalents.
- Query-embedding, live ChromaDB, LLM-generation, and GPU measurements are unavailable.
- CPU-utilization percentages were not reliably available. Wall time, process CPU time, and sampled Windows working set are retained in the raw artifacts.
- Benchmark source checksums were already validated in Phase 7.1; these timed runs verified file presence, byte sizes, chunk fingerprints, and embedding ID alignment without repeating the expensive source checksum pass.
- Docker operations were not performed.

## Files

- `runner.py`: reproducible local benchmark and reliability runner.
- `baseline_results.json`: unchanged baseline observations.
- `optimized_results.json`: unchanged optimized observations.
- `results.json`: consolidated measurements and final test status.
- `reproducibility.md`: commands, environment restrictions, and artifact hashes.

