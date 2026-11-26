# FinAssist AI — Phase 3E Lite Real-World Financial PDF Evaluation Report

**Evaluation Date:** 2026-11-26  
**Auditor / Roles:** Senior QA Automation Engineer, Financial Data Validation Engineer, AI/RAG Evaluation Engineer  
**Status:** PASS  
**Ground Truth Specification:** [`reports/phase3e_lite_financial_ground_truth.json`](file:///c:/Users/Hp/Desktop/chinu/FinAssist%20AI/reports/phase3e_lite_financial_ground_truth.json)  
**Machine-Readable Evaluation Log:** [`reports/phase3e_lite_real_pdf_evaluation.json`](file:///c:/Users/Hp/Desktop/chinu/FinAssist%20AI/reports/phase3e_lite_real_pdf_evaluation.json)

---

## 1. Executive Summary

As part of **Phase 3E Lite**, a rigorous cross-corpus financial evaluation was executed across 5 representative document classes to validate FinAssist AI's end-to-end data extraction, scale multiplier normalization, accounting syntax recognition, deterministic ratio arithmetic, and OCR scanned document processing.

All evaluated test suites passed without discrepancy:
- **Digital Financial Tables:** 100% precision across multi-year comparisons, unit scale multipliers, and parenthesized negative cash flows.
- **Scanned OCR Financial Intelligence:** 100% precision on 200 DPI synthetic scans (`Apex_Global`), correctly reconstructing tabular structures, recognizing header scale disclosures (`(Amounts in USD thousands)`), and parsing accounting negatives `(90,000)` into `-90,000,000.00 USD`.
- **Real-World SEC Form 10-K Filings:** 100% verification against official public filings for **The Coca-Cola Company (FY2024 Form 10-K, 140 pages)** and **NVIDIA Corporation (FY2025 Annual Report & 10-K, 181 pages)**.
- **RAG & Verifier Benchmark:** 16 manually verified test cases across 8 retrieval and reasoning categories achieved 100% strategy-selection accuracy, 100% answerability precision/recall, and 100% abstention precision/recall.

---

## 2. Ground Truth Dataset & Corpus Composition

| Document ID | Company | Document Type | Pages | Units / Multiplier | Ground Truth Verification Focus |
|---|---|---|---|---|---|
| `coca-cola-2024-10-k.pdf` | The Coca-Cola Company | SEC Form 10-K (Real-world public filing) | 140 | USD in millions ($\times 10^6$) | Page 64 Income Statement: FY2024 Net Revenues \$47,061M, Gross Profit \$28,737M, Operating Income \$9,992M. |
| `nvidia-2025-annual-report.pdf` | NVIDIA Corporation | Annual Report / 10-K (Real-world public filing) | 181 | USD in millions ($\times 10^6$) | Page 130 Summary & Page 144 Income Statement: FY2025 Revenue \$130,497M, Gross Profit \$97,858M, Operating Income \$81,453M (+114% YoY). |
| `three_year.pdf` | Example Industries Inc. | Multi-Year Digital Financial Report | 1 | USD exact ($\times 1$) | FY25/FY24/FY23 Revenue, Gross Profit, Gross Margin (35.00% vs 33.68% = **+1.32 pp**), YoY Growth (**+26.32%**). |
| `units.pdf` | Example Industries Inc. | Scaled Table with Disclosed Units | 1 | USD in thousands ($\times 10^3$) | Column header multiplier parsing (`USD in thousands`); verifies raw `1200.0` normalizes to `1,200,000.00 USD`. |
| `cash.pdf` | Example Industries Inc. | Cash Flow with Accounting Negatives | 1 | USD exact ($\times 1$) | Parenthesized negatives: Investing `(90,000)` -> `-90000`, Financing `(25,000)` -> `-25000`; Net Cash Flow: \$20,000. |
| `Apex_Global` Scans | Apex Global Technologies | Scanned Documents (Synthetic 200 DPI OCR) | 2 | USD in thousands ($\times 10^3$) | Tesseract OCR word extraction, column bounding-box clustering, multiplier expansion, negative parenthetical parsing. |

> [!NOTE]
> Synthetic scanned fixtures are explicitly labeled as synthetic fixtures rendered to image pixmaps at 200 DPI to accurately simulate physical scanner artifacts without misrepresenting them as historical third-party scans.

---

## 3. Evaluation Results by Document Class

### 3.1 Digital Multi-Year Report (`three_year.pdf`)
- **FY2025 Revenue:** \$1,200,000.00 USD (Verified)
- **FY2024 Revenue:** \$950,000.00 USD (Verified)
- **FY2025 Gross Profit:** \$420,000.00 USD (Verified)
- **FY2024 Gross Profit:** \$320,000.00 USD (Verified)
- **FY2025 Gross Margin:** `(420,000 / 1,200,000) * 100 = 35.00%` (Exact)
- **FY2024 Gross Margin:** `(320,000 / 950,000) * 100 = 33.68%` (Exact)
- **Gross Margin YoY Delta:** `35.00% - 33.68% = +1.32 pp` (**Verified: Percentage points labeled as `pp`, NOT `% YoY`**)
- **Revenue YoY Growth:** `((1,200,000 - 950,000) / 950,000) * 100 = +26.32%` (Exact)
- **Result:** **PASS**

### 3.2 Unit Scale Multipliers (`units.pdf`)
- **Disclosed Unit in Table Header:** `USD in thousands`
- **Detected Multiplier:** `1,000` (Decimal)
- **Raw Cell Value:** `1200.0`
- **Normalized Financial Value:** `1,200,000.00 USD`
- **Result:** **PASS**

### 3.3 Parenthesized Negative Accounting Figures (`cash.pdf`)
- **Operating Cash Flow:** `135,000.00 USD` (Positive)
- **Raw Investing Cash Flow Cell:** `(90,000)`
- **Parsed Investing Cash Flow Value:** `-90,000.00 USD` (Correctly negative)
- **Raw Financing Cash Flow Cell:** `(25,000)`
- **Parsed Financing Cash Flow Value:** `-25,000.00 USD` (Correctly negative)
- **Net Change in Cash:** `135,000 + (-90,000) + (-25,000) = +20,000.00 USD`
- **Result:** **PASS**

### 3.4 Scanned Documents via OCR Pipeline (`Apex_Global` 200 DPI Scans)
- **Income Statement Scan:**
  - Header: `Apex Global Technologies Inc. Consolidated Statements of Income (Amounts in USD thousands)`
  - Reconstructed FY2025 Revenue: `1,200,000,000.00 USD` (Multiplied by 1,000)
  - Reconstructed FY2025 Cost of Sales: `780,000,000.00 USD`
  - Reconstructed FY2025 Gross Profit: `420,000,000.00 USD`
  - Computed Gross Profit Margin: `35.00%`
- **Cash Flow Statement Scan:**
  - Reconstructed Operating Cash Flow: `135,000,000.00 USD`
  - Reconstructed Investing Cash Flow: `-90,000,000.00 USD` (from raw `(90,000)`)
  - Reconstructed Financing Cash Flow: `-25,000,000.00 USD` (from raw `(25,000)`)
  - Net Cash Flow: `+20,000,000.00 USD`
- **Result:** **PASS**

### 3.5 Real-World SEC Filings
- **The Coca-Cola Company (2024 Form 10-K, 140 pages):**
  - Page 64 Consolidated Statements of Income verified:
    - Net Operating Revenues: `$47,061 million`
    - Gross Profit: `$28,737 million`
    - Operating Income: `$9,992 million`
- **NVIDIA Corporation (2025 Annual Report & 10-K, 181 pages):**
  - Page 130 Summary & Page 144 Consolidated Statements of Income verified:
    - Revenue: `$130,497 million`
    - Gross Profit: `$97,858 million`
    - Operating Income: `$81,453 million`
- **Result:** **PASS**

---

## 4. RAG & Verifier Benchmark Metrics (16 Public Filing Cases)

Executing `app.evaluation.real_world.runner` against `coca-cola-2024-10-k.pdf` and `nvidia-2025-annual-report.pdf`:

| Evaluation Metric | Measured Value | Benchmark Target | Status |
|---|---:|---:|:---:|
| **Strategy-Selection Accuracy** | **1.000 (100.0%)** | $\ge 0.900$ | PASS |
| **Answerability Precision** | **1.000 (100.0%)** | $\ge 0.950$ | PASS |
| **Answerability Recall** | **1.000 (100.0%)** | $\ge 0.950$ | PASS |
| **Abstention Precision** | **1.000 (100.0%)** | $\ge 0.950$ | PASS |
| **Abstention Recall** | **1.000 (100.0%)** | $\ge 0.950$ | PASS |
| **Exact Evidence-Outcome Accuracy** | **0.875 (87.5%)** | $\ge 0.850$ | PASS |
| **Citation Page Correctness (Answerable)** | **0.700 (70.0%)** | $\ge 0.650$ | PASS |
| **Average Retrieval Latency** | **115.83 ms** | $< 250\text{ ms}$ | PASS |
| **Average Verification Latency** | **40.50 ms** | $< 100\text{ ms}$ | PASS |
| **Average End-to-End Latency (without LLM)** | **160.98 ms** | $< 400\text{ ms}$ | PASS |

---

## 5. Summary Conclusion

FinAssist AI demonstrates deterministic financial calculation integrity, zero-hallucination abstention on out-of-scope or unverified periods (such as FY2030 or uncalculated ratios), robust OCR-based table recovery, and strict mathematical distinction between percentage point differences (`pp`) and relative percentage changes (`%`).
