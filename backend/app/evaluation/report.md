# Phase 5 Retrieval Evaluation

Generated: 2026-11-03T06:33:52.674052+00:00

This is an actual offline retrieval run over the versioned synthetic benchmark. It uses the configured BGE model and the production BM25 tokenizer/RRF rules; it does not call the LLM or claim answer-quality results.

- Dataset: `finassist-phase5-retrieval-v1`
- Questions: 8
- Chunks: 10
- top_k: 3
- Embedding model: `BAAI/bge-small-en-v1.5`

| Configuration | Precision@K | Recall@K | MRR | nDCG@K | Avg latency (ms) |
|---|---:|---:|---:|---:|---:|
| A — Semantic only | 0.3750 | 1.0000 | 1.0000 | 1.0000 | 23.170 |
| B — Hybrid for all | 0.3750 | 1.0000 | 0.9167 | 0.9375 | 22.995 |
| C — Adaptive | 0.3750 | 1.0000 | 1.0000 | 1.0000 | 14.773 |

Adaptive strategy-selection accuracy: **100.00%**.

The corpus is intentionally small and synthetic, so these measurements validate the evaluation path rather than establish statistically general performance. Latency excludes one-time model loading and document embedding/index construction.
