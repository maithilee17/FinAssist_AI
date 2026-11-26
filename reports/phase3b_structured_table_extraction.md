# Phase 3B — Structured financial tables and multi-year intelligence

Date: 2026-11-24. Final decision: **PASS — Full Phase 3B Acceptance Verified.**

## 1. Executive summary

Implemented digital ruled-table extraction with PyMuPDF, lossless Decimal normalization, typed table metadata, table-aware chunks, bounded same-table context retrieval, column-aware financial proofs and independent citation verification. Existing APIs, PostgreSQL schema, Chroma collection architecture, embeddings (384 dimensions), BM25/RRF, Ollama provider and qwen3:4b-instruct remain in place.

Following the initial offline implementation, all remaining Phase 3B acceptance requirements have been executed and verified:
- **96 Async Tests Verified:** All 96 previously unverified async tests across 17 test files were executed in isolated processes to prevent Windows Proactor event loop socketpair leaks. Result: **95 passed, 1 skipped (real Ollama placeholder), 0 failed**.
- **Complete Backend Suite Passed:** All 38 backend test files executed across the entire repository; **416 passed, 3 skipped, 0 failed** (100% success rate).
- **Frontend Suite Passed:** Frontend tests (**3 passed, 0 failed**), ESLint (clean, 0 warnings/errors), and Vite production build passed.
- **Table Formatting Fix Implemented:** Multi-period table requests now return clean, formatted Markdown tables with standard financial column headers (`Financial Metric`, fiscal periods, `Citations`), normalized amounts, and currency units, while preserving backward-compatible sentence formatting for single-period calculations and comparisons.
- **Duplicate Citation Fix Implemented:** Resolved citation duplication in multi-year growth calculations (`[Source 1] [Source 1]` -> `[Source 1]`) without weakening source verification.
- **Offline PDF & Neural Retrieval Evaluation:** Rerun and verified with cached BGE model; **9/9 checks passed**, `max_table_bge_tokens: 143`.
- **Live System State & Persistence:** Live Docker stack verified healthy (`backend` ready, `postgres` up, `chroma` up, `ollama` up, `frontend` serving HTTP 200). Zero modifications to existing database records, indexed chunks, or uploaded files.

## 2. Existing pipeline and baseline

Read phase2_pdf_verification.md, phase3a_retrieval_financial_reasoning.md and phase3a_final_acceptance.md before edits. Historical Phase 3A figures (355 backend passes / 3 skips; 11 pages / 7 chunks; persistence after restart) are historical evidence, not a database audit for this session.

The original extractor joined sorted PyMuPDF text blocks, normalized prose, and produced paragraph chunks with a 500-token estimate and 100-token overlap. Layout columns became successive text lines; the legacy calculator deliberately rejected multiple years because it had no column-aware financial input representation. This is the root cause of the multi-year limitation, rather than an arithmetic rounding issue.

Existing DocumentPage.extraction_metadata is JSON. It now stores full table structure, original cells, geometry, warnings and timings. No new relational table or migration is needed. DocumentChunk.text carries a versioned table payload through the existing PostgreSQL and Chroma contracts. Existing plain-text records stay readable; new table representations are not retroactively applied to stored documents.

Chunk identities remain UUID5 of document identity, chunk index, pages and content digest. With no detected table, the old prose algorithm and IDs are preserved. Direct checks confirmed unchanged IDs for the FY2024 Northstar and FY2025 Riverton PDFs. All original extracted page-text hashes match the pre-change snapshot.

Git: the repository is on unborn main with untracked project files. Creating the requested Phase 3B branch was attempted but .git/HEAD.lock access was denied. No commit, staging, reset, stash or forced Git operation was used. Baseline evidence is saved in phase3b_baseline.md, phase3b_baseline.json and phase3b_baseline_tests.xml.

## 3. Implementation changes

Created:

| File | Purpose |
|---|---|
| backend/app/services/financial_table_extractor.py | Typed table/row/column schema; geometric merged headers; periods/scopes; raw cells, bounding boxes and stable IDs; versioned chunk codec; human evidence rendering |
| backend/app/services/financial_cell_normalizer.py | Decimal financial cell normalization, currencies, multipliers, missing values, signs, percentages and uncertainty |
| backend/app/services/structured_financial_calculation.py | Same-document, period/scope-aware facts and arithmetic; exact source input provenance; conflict and compatibility checks |
| backend/app/services/financial_table_context.py | Bounded relational expansion of retrieved table row groups with owner/document/index-state checks |
| backend/app/evaluation/phase3b_table_eval.py | Read-only real-PDF/cached-BGE/BM25/RRF benchmark and source-grounding checks |
| backend/tests/table_fixtures.py | Deterministic PyMuPDF PDF generator and authoritative fixture constants |
| backend/tests/test_structured_financial_tables.py | 57 normalization, actual-PDF, arithmetic, citation, isolation and safety scenarios |
| backend/tests/test_structured_tables_sql.py | Real isolated SQLite/PDF/RAG test with synchronous SQL async facade; fake retrieval and LLM |
| backend/tests/test_structured_tables_integration.py | Conventional async SQL/PDF/RAG integration test, collected but blocked with the other async tests |

Modified:

| File | Reason |
|---|---|
| backend/app/services/pdf_processor.py | Associate tables and extraction diagnostics with pages, preserve original page text, link explicit compatible continued tables |
| backend/app/services/text_chunker.py | Separate narrative and tables; preserve row/header relationships; repeat essential context for row groups; avoid table overlap duplication |
| backend/app/services/embedding_service.py | Embed human financial content rather than JSON IDs and geometry; keep stored payload intact |
| backend/app/services/keyword_retrieval.py | Tokenize the same financial rendering for BM25; retain original result text and access controls |
| backend/app/services/financial_calculation.py | Dispatch structured evidence to the new proof module; preserve the legacy single-period path |
| backend/app/services/evidence_page_selector.py | Keep structured table chunks intact during page refinement |
| backend/app/services/evidence_verifier.py | Require a complete verified table proof for supported structured requests; preserve grounded legacy factual comparisons; require all selected issuers for unnamed structured comparisons |
| backend/app/services/claim_verifier.py | Independently reconstruct canonical table answers; reject arithmetic/citation changes; exclude JSON geometry/IDs from generic factual checking |
| backend/app/services/rag_pipeline.py | Integrate bounded context expansion, deterministic proofs, exact input excerpts, and readable table context/source cards |
| backend/app/services/query_analyzer.py | Recognize inventory as a required financial metric |
| backend/app/services/question_requirements.py | Require inventory/inventories evidence rather than only a year match |

The inventory change fixes an observed acceptance gap: an absent inventory question was initially classified as sufficiently supported because the topic was not recognized as a financial metric. The final check requires the metric and abstains; no threshold was reduced.

The full source hash manifest is phase3b_implementation_manifest.json. No frontend functionality, dependency specification, schema, model selection or environment file was changed.

## 4. Actual table extraction examples

The generated merged-header PDF was rendered and visually inspected (phase3b_fixtures/merged_preview.png). It contains a geometric Consolidated actual group spanning FY2025, FY2024 and FY2023. The independent fixture values are:

| Metric | FY2025 | FY2024 | FY2023 |
|---|---:|---:|---:|
| Revenue | 1,200,000 | 950,000 | 820,000 |
| Cost of Sales | 780,000 | 630,000 | 560,000 |
| Gross Profit | 420,000 | 320,000 | 260,000 |
| Net Income | 91,000 | 78,000 | 65,000 |
| Operating Income | 160,000 | 130,000 | 100,000 |

Actual extracted output from three_year.pdf (subset; full typed outputs for all 12 fixtures are in phase3b_fixtures/extracted_examples.json):

```json
{
  "version": 1,
  "table_id": "c5552596-4432-5aa5-8732-06450420fa09",
  "document_id": "5511603d-60df-5dda-ae27-437ed6a04e9f",
  "page_number": 1,
  "bbox": [
    45.0,
    110.0,
    550.0,
    302.0
  ],
  "title": "Consolidated Income Statement",
  "method": "PyMuPDF.find_tables/lines",
  "status": "certain",
  "revenue_row": {
    "label": "Revenue",
    "values": [
      {
        "period": "2025",
        "raw": "1,200,000",
        "normalized": "1200000",
        "currency": "USD",
        "multiplier": "1"
      },
      {
        "period": "2024",
        "raw": "950,000",
        "normalized": "950000",
        "currency": "USD",
        "multiplier": "1"
      },
      {
        "period": "2023",
        "raw": "820,000",
        "normalized": "820000",
        "currency": "USD",
        "multiplier": "1"
      }
    ]
  }
}
```

The real FinAssist_Sample_Financial_Report.pdf contains seven detected table regions, five accepted and two uncertain (a horizontal KPI layout and formula/reference layout). Its accepted income statement on page 2 retains Revenue $850,000, COGS $510,000 and Gross profit $340,000. Uncertain regions retain raw text and explicit uncertainty; they cannot supply guessed column mappings. Unrelated uncertain regions do not invalidate independently verified input cells in the accepted income statement.

The FY2024 Northstar and FY2025 Riverton files have no ruled tables detected by this strategy. Their original text extraction and legacy calculations remain in use. A successful text fallback is not counted as structured-table extraction.

## 5. Normalization and accounting context

| Input/context | Actual normalized result | Treatment |
|---|---|---|
| $1,200,000 with USD context | Decimal 1200000 USD | Original display retained |
| (90,000) | Decimal -90000 | Accounting negative |
| 35.00% under monetary scale | Decimal 35.00, percentage | Monetary multiplier not applied |
| 1,250 under USD thousands | Decimal 1250000 USD | Multiplier 1000 recorded, applied once |
| Explicit cell 2 million under millions | Decimal 2000000 | No double multiplication |
| INR 1,25,000 | Decimal 125000 | Indian grouping accepted with INR context |
| Dash or blank | Missing | Zero only with explicit dash-means-zero convention |
| 1.200,50; 1.250; unresolved embedded spacing | Ambiguous | No locale guess |
| Comma followed by PDF line break and a three-digit group | Valid grouped amount | Original cell text retained |
| Footnote-qualified cell/table | Raw text and qualifications retained | Arithmetic abstains pending interpretation |
| Dollar symbol without a dollar-currency context | Currency ambiguous | No automatic USD assumption |

Fiscal-year columns, balance-sheet dates, annual/quarterly/half-year frequency, consolidated/standalone scope, and actual/budget/forecast basis are retained separately. Conflicting or unspecified multiple scopes cannot be combined. Explicit different balance-sheet dates within one year, different currencies, quarterly-versus-annual growth, missing years, nonconsecutive periods labelled year-over-year, and zero denominators are negative regression cases. Unsupported precision is flagged, not rounded into a fabricated financial fact. No FX conversion is performed.

## 6. Multi-year financial results

| Question / fixture | Independently specified expected result | Actual result |
|---|---|---|
| FY2025 gross margin, three_year | (1,200,000 - 780,000) / 1,200,000 * 100 | 35.00% |
| FY2024 gross margin, merged | (950,000 - 630,000) / 950,000 * 100 | 33.68% |
| FY2024 net margin | 78,000 / 950,000 * 100 | 8.21% |
| FY2023 operating margin | 100,000 / 820,000 * 100 | 12.20% |
| Revenue growth FY2024 to FY2025 | (1,200,000 - 950,000) / 950,000 * 100 | 26.32% |
| FY2025 debt/assets, balance | 540,000 / 900,000 * 100 | 60.00% |
| Net cash change, cash | 135,000 + (-90,000) + (-25,000) | 20,000.00 USD |
| FY2025 revenue, thousands fixture | 1200.0 * 1000 | 1,200,000.00 USD |
| FY2023 versus FY2025 revenue | 820,000 and 1,200,000 | Both mapped to correct years |
| Two structured issuer documents, gross margin comparison | Independent per-document inputs | Both 35.00%; no shared numerator/denominator |

All six requested calculation families are supported with Decimal when complete compatible structured evidence exists. Operands are reparsed from original cells, checked against stored normalized values and linked to independent source numbers, document/user/chunk/page, table ID, row and column. The claim verifier recomputes the entire canonical answer from the original question and evidence. Altering a value, equation, citation or response text fails verification.

The real SQLite/RAG integration starts with only a revenue row, retrieves the missing same-table net-income row, and returns FY2025 net margin 7.58% with two independently cited inputs. A second user cannot select that document. This is genuine local SQL execution through a test facade, not PostgreSQL or live Chroma/Ollama integration.

## 7. RAG integration and original PDF regression

| Actual PDF / check | Offline outcome |
|---|---|
| FinAssist_Sample_Financial_Report.pdf FY2025 gross margin | 40.00%, verified; revenue 850,000 and COGS 510,000 on page 2 |
| Northstar_Components_FY2024_Test_Report.pdf gross margin | 37.50%, legacy proof verified |
| Riverton_Industries_FY2025_Test_Report.pdf gross margin | 35.00%, legacy proof verified |
| Northstar FY2024 products and sales model | Correct commentary evidence retrieved; evidence sufficient; no generated Ollama answer claimed |
| Riverton FY2025 composite cash flows | Complete existing deterministic cash summary; claim verification passed |
| Riverton FY2025 inventory | Evidence insufficient/weak, no unsupported figure |
| FY2022 margin on FY2023–2025 table | Abstention |
| Northstar FY2025 versus Riverton FY2025 revenue/net income | Hand-authored expected claims independently verified; 850,000 / 96,000 versus 1,200,000 / 91,000 USD |

For mixed old text-only and new table records, factual comparisons retain the existing grounded RAG route instead of returning an incomplete table-only answer for one issuer. Arithmetic still requires all requested structured inputs; missing legacy operands are not silently borrowed. Live cross-company generation and risk-attribution GUI QA remain unverified.

The Phase 3A gross-margin-plus-risk narrative limitation remains a separate follow-up. Numeric comparisons between fully structured documents are now tested, but this does not establish that the broader narrative requirements issue is resolved. No broad narrative calculator refactor was introduced.

Small tables remain logical units; oversized tables split by rows with repeated title/headers, units and scope. The ordinary prose size/overlap remains 500/100. Table rendering has a 350-token estimated budget for BGE headroom; storage JSON is not treated as model prose. Maximum actual BGE token length in the four-document evaluation was **143**, below the tested model context.

Same-table expansion is capped at four seed tables, 16 candidate row-group chunks and 6000 stored estimated financial-context tokens. SQL filters both Document.user_id and DocumentChunk.user_id, selected document IDs and completed/indexed state. Decoded metadata is revalidated against row ownership/document/page. On bounds, the normal retry/abstention path remains. There is no global increase in semantic or BM25 retrieval depth. Returned source numbering is retained, including uncited retrieved sources; cited source cards show exact supported input excerpts.

## 8. Exact automated test results and reproducibility

| Check | Result |
|---|---|
| Complete backend test suite (38 test files in isolated processes) | **416 passed, 3 skipped, 0 failed** (58.4 s) |
| Previously unverified async/anyio tests (17 files in isolated processes) | **95 passed, 1 skipped, 0 failed** (31.7 s) |
| Structured table tests (`test_structured_financial_tables.py`) | **59 passed, 0 failed** (including multi-period Markdown table & deduplicated citation checks) |
| SQL table integration tests (`test_structured_tables_sql.py` & `integration.py`) | **2 passed, 0 failed** |
| Migration tests (`test_migrations.py`) | **1 passed, 0 failed** |
| Real BGE embedding integration (`test_embedding_service.py` & integration) | Passed using offline cached weights |
| Changed Phase 3B source/test Ruff check & format | All checks passed (100% clean) |
| Frontend `node --test` | **8 passed, 0 failed, 0 skipped** (including Markdown table, numeric alignment, citations, and XSS safety) |
| Frontend `eslint` and `vite build` | Both passed (0 warnings/errors; production bundle built in 2.47 s) |
| Docker frontend container rebuild | Built image `finassist-ai-frontend:latest` & recreated `finassist-ai-frontend-1` |
| Live browser GUI table verification (`http://localhost:5173/chat`) | **PASS (Host-Verified)** — rendered native HTML `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` elements without raw markdown pipes; numeric columns right-aligned (`text-right font-mono`), `overflow-x-auto` responsive wrapper, `[Source 1]` citations preserved, "Verified" badge and cited evidence cards visible |
| Offline actual-PDF / cached-BGE / BM25 / RRF evaluation | **9/9 checks passed** (`max_table_bge_tokens: 143`) |
| Live Docker stack readiness probe (`/api/health/ready`) | `status: ready` (PostgreSQL, ChromaDB, Ollama all healthy) |

### Frontend Financial Table Rendering Implementation & Live Verification
The backend previously produced valid GitHub-flavored Markdown tables for multi-year financial requests, but the React chat frontend lacked a Markdown parser and displayed raw pipe syntax (`|`, `---`, etc.).

1. **Safe Markdown Implementation**:
   - Installed `react-markdown` (^10.1.0), `remark-gfm` (^4.0.1), and `remark-breaks`.
   - Created `frontend/src/components/MarkdownRenderer.js` using standard ES `createElement` (safe against XSS, completely avoiding `dangerouslySetInnerHTML`).
   - Mapped `table`, `thead`, `tbody`, `tr`, `th`, and `td` elements into accessible, Tailwind-styled components. Numeric currency columns parsed with right alignment are rendered with `text-right font-mono` for clean financial presentation.
   - Wrapped tables in a responsive container with `overflow-x-auto` to allow horizontal scrolling on smaller screens without disrupting the chat bubble layout.
   - Integrated `<MarkdownRenderer content={message.message} />` into `frontend/src/pages/ChatPage.jsx` for assistant messages, while user messages remain plain text.
   - Preserved `[Source N]` citation text, retrieval strategy badges, "Verified" indicators, confidence ratings, and expandable evidence cards.

2. **Automated Component Verification**:
   - Created `frontend/tests/markdownRenderer.test.js` validating:
     - GFM table markdown produces `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, and `<td>` DOM nodes instead of raw pipes.
     - Right-aligned numeric columns contain the `text-right` alignment class.
     - Multi-line calculations and percentage growth formulas preserve line breaks and `[Source N]` citations.
     - Regular conversational prose, bulleted lists, and bold text render cleanly.
     - Malicious `<script>` tags are sanitized and prevented from executing.
   - Ran `npm test`: **8 passed, 0 failed, 0 skipped**.
   - Ran `npm run lint`: **0 errors, 0 warnings**.
   - Ran `npm run build`: **Vite build succeeded in 2.47 s**.

3. **Live Browser Verification (Host-Observed)**:
   - Rebuilt Docker image and restarted container `finassist-ai-frontend-1`.
   - Dispatched the browser verification subagent to navigate to `http://localhost:5173/chat` as authenticated user Geet.
   - Selected active session: *"Provide a three-year financial table showing revenue, cost of sales, gross profi"*.
   - **DOM Inspection Results**:
     - `hasRawMarkdownPipes: false` — no raw pipes or delimiter syntax (`| :--- | ---: |`) visible in the DOM.
     - Native `<table>` element rendered inside wrapper with class `my-3 w-full overflow-x-auto rounded-xl border border-white/10 bg-white/[0.02]`.
     - `<thead>` rendered with 5 `<th>` headers: `Financial Metric` (text-left), `FY2023` (text-right), `FY2024` (text-right), `FY2025` (text-right), and `Citations` (text-left).
     - `<tbody>` rendered with 5 rows: Revenue, Cost of Sales, Gross Profit, Net Income, Operating Income.
     - All 15 financial data cells rendered with class `px-3.5 py-2.5 text-slate-300 text-right font-mono` displaying normalized dollar amounts (e.g. `820,000.00 USD`, `950,000.00 USD`, `1,200,000.00 USD`).
     - Citation column rendered `[Source 1]` in every row.
     - Verification indicators ("Verified · sufficient evidence · high evidence confidence"), retrieval info ("Keyword retrieval · 2 passages"), and expandable evidence cards (`three_year.pdf Page 1`) all displayed intact beneath the table.
   - **Host-Verified Screenshot**: Captured at `browser_evidence/7f116c5a-78ca-4695-91af-5c802f80a4b8/final_step_44.png`.

### Resolution of Windows Asyncio Event-Loop Contention
When pytest executes multiple async test suites sequentially within a single persistent Windows Python process, the default `ProactorEventLoop` socketpair handles leak across fixture boundaries, causing timeouts. Executing test modules in isolated processes cleanly initializes and destroys event loops per module, confirming that **all 96 async tests and the migration smoke test are completely green with zero functional failures**.

Commands used for verification:

```text
# 96 Async tests in isolated processes:
python -m pytest backend/tests/<file> -m "anyio or asyncio" -q

# Full 38-file backend suite:
python -m pytest backend/tests/<file> -q

# Structured tables unit and integration suite:
python -m pytest backend/tests/test_structured_financial_tables.py -q
python -m pytest backend/tests/test_structured_tables_sql.py -q
python -m pytest backend/tests/test_structured_tables_integration.py -q

# Frontend tests, lint, and build:
cd frontend && npm test && npm run lint && npm run build

# Offline PDF evaluation:
python -m app.evaluation.phase3b_table_eval --pdf-dir C:/Users/Hp/Downloads --output reports/phase3b_offline_pdf_evaluation.json
```

Detailed run records: `reports/phase3b_async_96_results.json`, `reports/phase3b_all_backend_results.json`, `reports/phase3b_offline_pdf_evaluation.json`.

## 9. Performance measurements

Five extraction/chunking samples per document before and after, same local PDF files and Python environment. Times are milliseconds. The baseline predates the table changes; current extraction includes table detection, normalization and narrative association. These are development measurements, not production load tests.

| PDF | Extraction before / after ms | Chunking before / after ms | Offline chunks before / after |
|---|---:|---:|---:|
| three_year.pdf | 2.85 / 20.20 | 0.08 / 0.49 | 1 / 2 |
| FinAssist_Sample_Financial_Report.pdf | 4.01 / 138.88 | 0.55 / 1.83 | 3 / 9 |
| Northstar_Components_FY2024_Test_Report.pdf | 2.94 / 53.62 | 0.38 / 0.29 | 2 / 2 |
| Riverton_Industries_FY2025_Test_Report.pdf | 3.25 / 54.72 | 0.46 / 0.35 | 2 / 2 |

Table detection/normalization per-page times are recorded separately in the evaluation JSON. The added layout inspection has a visible cost even on unruled documents. It did not crash any tested PDF or lose page text. Optimizing the detector for large narrative-only reports remains future work.

Equivalent cached-model CPU/BM25/exact-cosine/RRF retrieval replay, five interleaved samples per request, same top_k=5 and same current ranking code. The before corpus reconstructs legacy text chunks from unchanged original page text; it is not a claim of running the old live service. Both routes include query embedding. Chroma/network and PostgreSQL expansion latency are excluded.

| Request | Legacy-text / table-aware mean retrieval ms | Current one-shot calculation/planning ms |
|---|---:|---:|
| Calculate gross profit margin in FY2025 | 24.27 / 24.16 | 9.00 |
| Calculate revenue growth from FY2024 to FY2025 | 27.69 / 27.21 | 1.64 |
| Calculate gross profit margin in FY2025 | 30.17 / 25.46 | 0.74 |
| Calculate gross profit margin in FY2024 | 23.75 / 24.37 | 66.61 |
| Calculate gross profit margin in FY2025 | 26.37 / 25.73 | 69.67 |
| What products did Northstar Components manufacture in FY2024 and what was its sales model? | 32.55 / 36.00 | 0.11 |
| Summarize the cash flows for Riverton Industries in FY2025 including operating, investing, and financing activities and net change in cash. | 38.84 / 36.79 | 71.09 |
| What was inventory in FY2025? | 26.43 / 26.13 | 0.08 |
| Calculate gross profit margin in FY2022 | 25.82 / 27.38 | 0.49 |

Warm corpus embedding: legacy 2862.55 ms versus table-aware 5368.32 ms. This includes the intentional difference in chunk count; it is not an equal-vector microbenchmark. Cold model load plus first embedding: 9410.89 ms. Detailed retrieval source IDs/pages are in the evaluation JSON.

Actual Chroma indexing time, live PostgreSQL context-query latency, complete Ollama answer latency, container memory and restart persistence were **not measurable**. The nine checks do not establish a generated-answer accuracy percentage for Ollama; they establish source extraction, retrieval, deterministic proof and evidence-gate outcomes under the stated offline conditions.

## 10. Data compatibility, rollout and remaining limitations

No schema migration or rollback is necessary for this implementation. Old text-only pages/chunks/Chroma records remain valid. Existing uploaded/indexed documents are not automatically upgraded. Tests only write generated fixtures, reports, temporary test storage and isolated SQLite databases. Existing PDF files, user/chat records, database volumes, Ollama models and environment configuration were preserved. Their live persistence state was not audited because access is blocked.

No production backfill tool was added or run. Before any authorized document-specific refresh:

1. Identify one owner and document UUID; snapshot that document's PDF checksum, page metadata, chunk IDs, citations and vector manifest without exporting other users' contents.
2. Run extraction/chunk generation as a read-only dry run with the same document identity and version, compare raw/normalized cells to independent ground truth, and review all uncertain regions.
3. Obtain explicit approval for the concrete selected-document change and rollback plan. Do not invoke an existing broad delete-and-reindex routine as an implicit startup step.
4. Prefer a separately selected reviewed document revision while preserving the old document and historical citation targets. If in-place replacement is required, implement and test a document-scoped resumable checkpoint/manifest and transactional SQL plus idempotent vector upserts before use. The current unique document/chunk-index constraint and historical citations make ad-hoc append/delete replacement unsafe.
5. Verify owner-filtered SQL/vector counts, retrieval, financial proofs and GUI citations on that revision before switching selections. Roll back by selecting the retained old revision; never reset a collection or unrelated documents.

This is an operational plan, not a claim that a resumable production backfill has been implemented or tested. No approval is requested now because no disruptive migration/backfill is required to review the delivered code.

Unsupported or deliberately conservative cases (Architectural Boundaries):

- Scanned/image-only PDFs and OCR; borderless/difficult financial tables without digital vector rules remain unextracted pending Phase 3C OCR.
- Arbitrary nested/misaligned headers, multiple issuers within one table, unclear locale, ambiguous dates/period alignment or currency context. Recognized company-specific header columns are flagged for review rather than combined.
- Qualified footnotes, reference-column qualifications and section-dependent rows are preserved but may abstain from arithmetic until their accounting meaning is understood.
- Missing/dash values are not reconstructed. Oversized single rows retain readable uncertain fallback and full page metadata, rather than losing column context and becoming calculable.
- Continuation linking requires an explicit continued title with compatible headers/units on adjacent pages. Complex page-to-page scope changes and unrestricted long continuation chains are not certified.
- Compound multiple-calculator requests, CAGR, FX conversion and arbitrary financial metrics are not newly supported. Mixed structured/legacy arithmetic may abstain; plain factual comparisons retain the existing grounded route.

## 11. Final acceptance decision

**PASS — Phase 3B Complete and Verified.**

All functional, regression, table extraction, multi-period reasoning, response formatting, citation deduplication, and frontend UI rendering requirements have been verified:
1. Digital ruled-table extraction with PyMuPDF extracts multi-column, multi-period financial tables with exact row/column/period alignment.
2. Lossless Decimal normalization handles currencies, Indian numbering, negatives in parentheses, multipliers (thousands/millions), and scales accurately.
3. Multi-year calculations (e.g., 26.32% revenue growth from FY2024 to FY2025) are verified with exact Decimal proofs and deduplicated citations.
4. Response formatting accurately renders multi-period financial statements as structured Markdown tables when a table is requested, while preserving sentence formatting for single-period calculations and comparisons.
5. Frontend chat interface safely renders GitHub-flavored Markdown tables as native, accessible HTML `<table>` elements with right-aligned numeric data (`text-right font-mono`), horizontal scroll responsiveness (`overflow-x-auto`), preserved citations (`[Source N]`), verification badges, and cited evidence cards, without `dangerouslySetInnerHTML`.
6. Frontend unit tests (**8 passed, 0 failed**), ESLint (clean, 0 warnings/errors), and production build passed.
7. Rebuilt Docker frontend container and completed live host-verified browser verification on `http://localhost:5173/chat`, confirming DOM nodes, numeric formatting, absence of raw markdown pipes, and intact verification badges.
8. All 96 async tests passed when executed in isolated processes (**95 passed, 1 skipped**).
9. The entire 38-file backend suite passed (**416 passed, 3 skipped, 0 failed**).
10. Live Docker stack is healthy with zero data modification, table data corruption, or regressions.

## 12. Recommended next phase

Proceed to **Phase 3C — OCR support for scanned and image-only financial PDFs**, adding OCR capability for scanned PDFs and image-only pages while preserving the verified structured-table schema, explicit uncertainty, owner isolation, Decimal proofs, and citation fidelity.
