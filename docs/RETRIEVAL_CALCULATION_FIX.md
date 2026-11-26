# Retrieval and financial calculation repair — 2026-11-16

## Findings and verification boundary

The current keyword branch passes keyword results directly downstream. RRF executes
only for hybrid mode, deduplicates chunk UUIDs, and preserves metadata; a zero fusion
count in keyword mode meant not executed, not lost passages. The UI now says so.
No RRF algorithm change was justified. Keyword and semantic services retain their
existing user/document filters; no broad fallback or unfiltered search was added.

The query analyzer classified the reported question as general because metric
classification required a year, number, or currency. Exact metric terms still
selected keyword search. The claim verifier compared number strings literally,
so 40.00% differed from 40%, and a newly computed percentage absent from the text
was rejected. This reproduces a confirmed failure class. The reported one checked
claim indicates post-generation rejection, rather than the pre-generation evidence
abstention (which records zero checked claims). The exact historical generated
sentence and private PDF passages were not available here; their particular rejection
cannot be proven from diagnostics alone. No claim of live PDF reproduction is made.

## Changes

- Added `financial_calculation.py`: labelled input extraction, Decimal arithmetic,
  explicit formula, derived result, and supporting citations for gross/net/operating
  margins, total-liabilities-to-assets, current ratio, gross profit and working capital.
- Calculation queries use hybrid retrieval. Existing exact-year facts and conceptual
  retrieval retain their branches. Equivalent gross-margin wording is covered.
- Evidence verification can establish sufficiency by independently checking all
  required arithmetic inputs, without lowering general lexical thresholds.
- Calculation passages retain their original pages instead of narrowing to one page
  and potentially dropping an operand. User/document validation still applies.
- RAG emits a deterministic calculation when verified inputs are available, rather
  than asking Ollama to invent or approximate arithmetic. Missing/ambiguous explicit
  calculation inputs abstain after the existing bounded retrieval expansion.
- Claim verification independently recomputes the canonical calculation and checks
  the exact answer and citations. Other generated claims retain normal verification.
  Decimal normalization also permits numerically equal percentage formatting.
- Stated-value questions without calculation intent retain the ordinary verification
  path if inputs for derivation are absent.
- UI labels fusion as Not executed for keyword/semantic mode; API numeric contracts
  remain unchanged. Hybrid still reports the actual fused count.

Files: backend/app/services/{financial_calculation,query_analyzer,adaptive_retrieval,
claim_verifier,evidence_verifier,evidence_page_selector,rag_pipeline}.py;
backend/tests/test_financial_calculation.py; frontend/src/pages/ChatPage.jsx;
this report. No dependency, environment, model, database or migration change.

## Calculation limits

The calculator deliberately accepts only clear labelled monetary lines with explicit
currency and optional thousand/million/billion scale. It does not guess values from
ambiguous multi-column tables, missing currencies, conflicting repeated figures,
multiple documents, multiple years, or explicitly requested years. These cases
remain conservative rather than silently combining unrelated inputs. Debt-to-assets
uses the disclosed total liabilities / total assets convention and shows that formula.
No guarantees are made for multi-entity reports without a structured entity parser.
The calculator uses the original retrieved passages and never searches global data.

## Validation

- 76 targeted backend tests passed, including 21 new calculation/citation/isolation
  cases and existing fusion, query, claim/evidence, configuration and vector checks.
- Correct results: gross margin 40.00%, net margin 11.29%, debt-to-assets 60.00%,
  current ratio 1.875x, operating margin 20.00%, gross profit USD 340000.00,
  working capital USD 140000.00. Multi-page operand citations survive verification.
- Unsupported altered results, missing inputs, zero denominator, conflicting amounts,
  mixed currencies, multiple years/documents and foreign ownership are rejected.
- Existing RRF regressions cover duplicate chunks and empty semantic results. No
  fusion defect was found. Existing async adaptive orchestration tests remain in place.
- Full backend suite attempted with a 45-second watchdog; stalled after its first
  test and was terminated. Async tests cannot be claimed passed in this restricted
  Windows execution environment (event-loop initialization was blocked in prior
  diagnosis). Authentication/upload/real pipeline acceptance remains to rerun locally.
- Backend Ruff passed. Frontend tests: 3 passed; ESLint and production build passed.
- Docker Compose configuration validation passed without printing resolved secrets.
- Host Ollama tags, backend live and ready endpoints were unreachable. Container
  Ollama diagnostic failed because Docker engine named-pipe access was denied.
  Neither live inference nor end-to-end PDF acceptance was verified.

No .env edits, model downloads, qwen3:4b-instruct changes, volume operations, uploads,
user/chat data writes, migrations, Docker rebuilds or restarts were performed.

## Safe operator rebuild and acceptance

From the project root, in a terminal with Docker access:

```powershell
docker compose config --quiet
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
docker compose exec -T backend python -m app.diagnostics.ollama
Invoke-RestMethod http://localhost:8000/api/health/live
Invoke-RestMethod http://localhost:8000/api/health/ready
```

These preserve volumes. The existing backend startup applies any pending migrations;
this repair adds none. Rebuild frontend too to see the diagnostic wording change.
Do not use down -v, volume pruning or database resets.

In a working backend Python environment:

```powershell
python -m pytest -q
python -m ruff check app tests
```

Then log into the existing account and ask the sample-PDF calculation questions.
Confirm formula/operands/result/citations, deliberately request a missing metric,
and test another account's isolation. Run opt-in real Ollama generation separately
only if desired; it was not run successfully here.
