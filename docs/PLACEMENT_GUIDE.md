# FinAssist AI Placement Guide

## Thirty-second explanation

FinAssist AI lets a user upload financial reports and ask questions whose answers must come from those reports. It combines exact-term BM25 search with BGE semantic search, chooses a retrieval route from the question, and fuses hybrid rankings with Reciprocal Rank Fusion. Before calling a configured language model it checks whether the retrieved evidence is sufficient. After generation it validates material claims and citations; when evidence is missing, it abstains instead of inventing a financial value.

## Problem and differentiator

Ordinary chatbots can produce plausible but unsupported figures. Financial questions also mix exact terms—company names, fiscal years, currencies, metrics—with conceptual language. FinAssist addresses both problems:

- hybrid retrieval covers exact and paraphrased questions;
- user/document filters protect tenant isolation;
- page-aware chunks preserve traceability;
- evidence gating prevents generation when requirements are missing;
- claim/citation validation removes or withholds unsupported material statements;
- confidence explains evidence quality without pretending to be factual probability.

## Feature summary

- Argon2 registration/login, expiring JWT cookie sessions, CSRF protection, and protected routes.
- Private PDF upload with size, type, structure, encryption, corruption, and ownership checks.
- Page-aware PyMuPDF extraction and conservative financial text cleaning.
- Stable overlapping chunks, BGE embeddings, and ChromaDB vector metadata.
- Cached per-user BM25, semantic search, transparent adaptive routing, and RRF.
- Evidence sufficiency, bounded retrieve-more, safe abstention, claim/citation validation, and explainable confidence.
- Persistent chat history, retrieval diagnostics, citations, excerpts, and responsive UI.
- Reproducible synthetic, real-report, end-to-end, and performance evaluation artifacts.

## Evaluation story

### What was actually evaluated

- Phase 5 synthetic retrieval: eight labelled questions comparing semantic-only, always-hybrid, and adaptive retrieval.
- Phase 6 synthetic evidence evaluation: eight labelled cases comparing no verification, evidence gating, and claim validation without an external provider call.
- Phase 7.1 real-world evaluation: 16 questions across eight categories using official NVIDIA FY2025 and Coca-Cola 2024 filings, 662 chunks, real cached BGE vectors, production retrieval/verification services, and no LLM generation.
- Phase 7.2 environment-limited running-application checks using persistent SQLite; live PostgreSQL, ChromaDB, and LLM remained unavailable.
- Phase 7.3 CPU reliability/performance observations, including PDF processing and evaluation-only exact-cosine equivalence.
- Phase 7.4 UI, production-configuration, lint, build, and bounded backend regression checks.

### Honest headline results

The 16-case Phase 7.1 run reported strategy-selection accuracy **1.000**, evidence-outcome exact accuracy **0.875**, answerability and abstention precision/recall **1.000/1.000**, citation-page correctness **0.700**, and fully supported reference claims **0.600**. Mean pipeline latency without an LLM was **668.170 ms**. Generated-answer correctness and LLM cost were unavailable because generation was disabled.

These results demonstrate the evaluation method and expose weaknesses; they do not prove general accuracy. The two-company dataset is small, citation correctness leaves clear room for improvement, and production PostgreSQL/ChromaDB/provider behavior remains unverified.

## Resume bullet options

Choose two or three and adapt the wording to the job description:

1. Built a full-stack financial-document RAG system with React, FastAPI, PostgreSQL, ChromaDB, BGE embeddings, BM25, adaptive routing, and Reciprocal Rank Fusion, with server-side tenant isolation and page-level citations.
2. Designed an evidence-aware answer policy that checks metric/period coverage, performs bounded retrieve-more, validates material claims and citations, and safely abstains when financial evidence is insufficient.
3. Created reproducible retrieval and reliability evaluations using 16 labelled questions across two official annual reports and 662 chunks; reported 70% citation-page correctness and 668 ms mean pipeline latency without an LLM, while explicitly documenting environment and dataset limits.

Do not replace the measured values with higher synthetic or estimated numbers.

## Demo walkthrough

1. Explain the problem: a confident answer without a source is unsafe for financial analysis.
2. Register and show that protected pages require the cookie-backed session.
3. Upload an approved report and explain extraction, page preservation, stable chunking, BGE indexing, and status transitions.
4. Ask an exact metric/year question and show why keyword or hybrid retrieval was selected.
5. Open a source card and match filename, page, excerpt, and claim support.
6. Ask a conceptual question to demonstrate semantic retrieval.
7. Ask a two-period comparison to demonstrate hybrid/RRF and requirement coverage.
8. Ask for an absent metric or future period and show the abstention.
9. Explain that confidence measures evidence signals, not truth probability.
10. End with the real evaluation results and unresolved limitations.

If staging services or an LLM are unavailable, use the recorded reports and screenshots and say so explicitly rather than simulating a live pass.

## Interview questions and answers

### Why use RAG instead of fine-tuning?

The knowledge changes per user's uploaded documents. RAG keeps source text outside model weights, supports deletion and user isolation, and returns traceable passages. Fine-tuning may shape behavior but is not a safe substitute for retrieving current private facts.

### Why combine BM25 and embeddings?

BM25 is strong for exact fiscal years, metric names, dates, and figures. Embeddings handle paraphrases and conceptual questions. The query analyzer avoids paying both costs for every query, while hybrid mode covers questions needing both signals.

### Why RRF instead of adding scores?

BM25 scores and cosine similarities have unrelated scales. RRF uses ranks, deduplicates by stable chunk ID, and avoids an arbitrary normalization formula.

### How is user isolation enforced?

The API derives the user from the verified token, checks ownership in PostgreSQL, builds BM25 only from that user's chunks, and applies a mandatory user filter inside Chroma queries. Inaccessible IDs return 404 where appropriate.

### How does evidence verification work?

The question analyzer extracts required metrics, periods, comparison sides, companies, units, and topics. Retrieved passages must be relevant, have valid ownership/page metadata, and cover those requirements. Weak coverage can trigger bounded retrieval expansion; missing coverage causes abstention.

### How are hallucinations handled?

The design reduces unsupported output but does not claim to eliminate hallucinations. It gates generation on evidence, separates system instructions from untrusted PDF text, checks claims and citations after generation, removes unsupported portions, and abstains when support remains inadequate.

### What does confidence mean?

It is a deterministic evidence-quality score derived from retrieval relevance, evidence sufficiency, claim support, and citation validity. It has not been statistically calibrated and must not be interpreted as the probability that an answer is true.

### How do citations avoid LLM fabrication?

The API constructs citation objects from retrieved chunk metadata. The model cannot create a valid source ID or page; the verifier rejects references outside the retrieved set.

### What are the biggest technical limitations?

No OCR, imperfect complex-table extraction, synchronous extraction/indexing, process-local BM25 caches, heuristic evidence/entailment rules, a small evaluation corpus, and no completed production PostgreSQL/ChromaDB/HTTPS/provider acceptance.

### What would you improve next?

First complete staging acceptance and browser automation. Then add background workers, authenticated PDF viewing, shared/versioned keyword-index invalidation, larger human-labelled evaluations, threshold calibration, dependency scanning, and operational telemetry.
