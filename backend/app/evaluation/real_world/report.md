# Phase 7.1 Real-World Financial Document Evaluation

Generated: 2026-11-26T02:51:26.022029+00:00

## Scope and provenance

Two official public annual-report PDFs were checksum-validated and passed through the production PyMuPDF extraction, page-aware chunking, BGE embeddings, BM25, adaptive routing/RRF, evidence verification, claim verification, citation checks, and confidence scoring.

| Company | Report | PDF pages | Chunks | SHA-256 |
|---|---|---:|---:|---|
| NVIDIA Corporation | [NVIDIA 2025 Annual Report](https://investor.nvidia.com/financial-info/annual-reports-and-proxies/default.aspx) | 181 | 350 | `757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc` |
| The Coca-Cola Company | [The Coca-Cola Company 2024 Form 10-K](https://investors.coca-colacompany.com/filings-reports/annual-filings-10-k/content/0000021344-25-000011/ko-20241231.htm) | 140 | 315 | `96da013cf58c651ae82253c926bfe5bbd1ae63fbcdd4da03efaecf363da11963` |

## Automatically measured results

The dataset has **16 cases**, **8 categories**, and **2 companies**.

| Metric | Result |
|---|---:|
| Strategy-selection accuracy | 1.000 |
| Exact evidence-outcome accuracy | 0.875 |
| Answerability precision / recall | 1.000 / 1.000 |
| Abstention precision / recall | 1.000 / 1.000 |
| Citation-page correctness on answerable cases | 0.700 |
| Reference claims fully supported | 0.600 |
| Additional-retrieval frequency | 0.500 |
| Mean retrieval latency | 115.834 ms |
| Mean verification latency | 40.504 ms |
| Mean pipeline latency without LLM | 160.981 ms |
| Generated-answer correctness / LLM cost | Not measured / no LLM call |

| Case | Category | Expected → observed strategy | Expected → observed evidence | Citation page | Decision |
|---|---|---|---|---:|---|
| nvidia-exact-revenue-2025 | exact_numerical | keyword → keyword | sufficient → sufficient | False | answer_permitted |
| nvidia-operating-income-2025 | financial_metric | keyword → keyword | sufficient → sufficient | False | answer_permitted |
| nvidia-revenue-comparison | reporting_period_comparison | hybrid → hybrid | sufficient → sufficient | True | answer_permitted |
| nvidia-data-center-drivers | conceptual | hybrid → hybrid | sufficient → sufficient | True | answer_permitted |
| nvidia-supply-transition-risks | multiple_passages | hybrid → hybrid | sufficient → sufficient | True | answer_permitted |
| nvidia-missing-debt-equity | missing_evidence | keyword → keyword | weak → weak | n/a | abstained |
| nvidia-ambiguous-profit | ambiguous_wording | keyword → keyword | weak → weak | False | abstained |
| nvidia-future-period | abstention | keyword → keyword | insufficient → weak | n/a | abstained |
| coke-exact-revenue-2024 | exact_numerical | keyword → keyword | sufficient → sufficient | True | answer_permitted |
| coke-operating-income-2024 | financial_metric | keyword → keyword | sufficient → sufficient | True | answer_permitted |
| coke-margin-comparison | reporting_period_comparison | hybrid → hybrid | sufficient → sufficient | True | answer_permitted |
| coke-operating-income-factors | conceptual | hybrid → hybrid | sufficient → sufficient | True | answer_permitted |
| coke-volume-and-revenue | multiple_passages | hybrid → hybrid | sufficient → sufficient | False | answer_permitted |
| coke-missing-debt-equity | missing_evidence | keyword → keyword | weak → weak | n/a | abstained |
| coke-ambiguous-performance | ambiguous_wording | hybrid → hybrid | weak → weak | n/a | abstained |
| coke-future-period | abstention | keyword → keyword | insufficient → weak | n/a | abstained |

## Manual versus automatic review

Expected answers, page labels, evidence excerpts, intended strategies, and intended verification outcomes in `dataset.json` were manually transcribed and reviewed against the two PDFs. Retrieval ranks, page intersections, verifier decisions, claims, confidence values, and latencies in `results.json` are automatically measured. Generated-answer correctness was not measured because LLM calls were deliberately disabled.

## Environment limitations

Docker Desktop was not running, so the external ChromaDB service could not be exercised. An evaluation-only exact cosine store replaced Chroma while preserving the production BGE model, `SemanticRetrievalService`, user/document filters, BM25, adaptive routing, and RRF. Consequently, this run tests semantic relevance but not Chroma HTTP behavior or approximate-index latency. No LLM provider was called.

These results characterize this small, versioned dataset only. They do not establish general financial-QA accuracy or eliminate hallucination risk.

## Bugs found and narrowly scoped fixes

- BM25 tokenization retained question stopwords and ranking over-weighted boilerplate. Stopwords are now removed and metric/year proximity contributes to deterministic reranking.
- Plural metrics such as `margins` and the financial metric `unit case volume` were not analyzed correctly. The rule-based analyzer now recognizes them.
- Evidence sufficiency could accept a metric and reporting period occurring far apart in one large chunk. Metric, period, and numeric evidence must now co-occur in a bounded local window.
- Unreported ratios and ambiguous terms such as bare `profit` or broad `performance` could be treated as answerable. They now require explicit ratio evidence or clarification.
- Citation-only fragments after sentence punctuation were detached from the preceding claim. Claim extraction now attaches them before verification.

## Remaining observed failures

Manual review is recorded in `manual_review.json`. The remaining failures are retrieval of NVIDIA consolidated revenue/operating-income summary passages, exact endpoint support for the NVIDIA comparison, and retrieval of Coca-Cola's page-7 worldwide unit-case values. No dataset-specific production workaround was added. The evidence verifier can still overestimate sufficiency when a chunk contains related numeric material but not the specifically requested value; claim verification caught the evaluated combined claims.

## Reproduction

From `backend/` on Windows PowerShell:

```powershell
$env:HF_HOME = (Resolve-Path '.model-cache')
$env:HF_HUB_OFFLINE = '1'
.\.venv\Scripts\python.exe -m app.evaluation.real_world.runner
```
