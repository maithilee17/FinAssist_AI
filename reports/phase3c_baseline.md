# Phase 3C — OCR and Scanned Financial PDF Intelligence: Baseline & Inspection Report

**Date:** 2026-11-24  
**Project:** FinAssist AI  
**Author:** Senior AI Architect, OCR Engineer, RAG Engineer, QA Engineer  
**Branch:** `phase3c`  
**Initial Decision:** BASELINE ESTABLISHED — Ready for Phase 3C Implementation.

---

## 1. Executive Summary & Objective

Phase 3C extends the FinAssist AI document intelligence platform to support scanned, image-only, mixed-content, and rotated financial PDFs. The system must recognize multi-period financial tables from scanned documents, reconstruct structured table representations, extract lossless `Decimal` financial amounts, and preserve document isolation, verified citations, and deterministic calculations without guessing missing figures via LLMs.

This report establishes the verified baseline prior to Phase 3C code modifications.

---

## 2. Repository & Version Control Status

- **Working Directory:** `C:\Users\Hp\Desktop\chinu\FinAssist AI`
- **Git Branch:** Switched to dedicated branch `phase3c`.
- **Git State:** Clean branch off `main`; existing project files preserved.
- **Safety Guarantee:** Zero modifications or deletions to existing uploaded PDFs, PostgreSQL database records, ChromaDB vector collections, or Ollama settings.

---

## 3. Historical Baseline & Regression Targets

Prior to Phase 3C, the verified Phase 3B acceptance baseline achieved:

| Component | Historical Baseline Result | Current Verification Status |
|---|---|---|
| Complete Backend Test Suite | **416 passed, 3 skipped, 0 failed** (38 test files) | Verified runnable; `test_structured_financial_tables.py` (59 passed), `test_pdf_processing.py` (6 passed) |
| Isolated Async Backend Tests | **95 passed, 1 skipped, 0 failed** (17 test files) | Verified; isolated process execution avoids Windows Proactor socketpair leaks |
| Frontend Test Suite | **8 passed, 0 failed, 0 skipped** | Verified (`node --test` in `frontend/`) |
| Frontend Code Quality | ESLint (0 errors, 0 warnings), Vite production build clean | Verified (`npm run lint`, `npm run build`) |
| Offline PDF Evaluation | **9/9 checks passed** (`max_table_bge_tokens: 143`) | Verified via cached BGE weights |
| Live Docker Stack | All 4 services healthy (`backend`, `frontend`, `postgres`, `chroma`) | Verified up and healthy (`/api/health/ready` returns ready) |
| Live HTML Financial Table | Rendered HTML `<table>` with right-aligned numeric cells | Verified via browser agent on `http://localhost:5173/chat` |

---

## 4. Current Pipeline Inspection

### 4.1 Ingestion & PDF Processing (`app/services/pdf_processor.py`)
- Opens PDFs safely using PyMuPDF (`pymupdf.open(path)`).
- Validates `%PDF-` magic header (first 1024 bytes), verifies `is_pdf`, checks encryption password rejection (`needs_pass`), and ensures `page_count >= 1`.
- Iterates over pages and calls `page.get_text("blocks", sort=True)`.
- **Current Limitation:** Scanned or image-only pages contain no native text blocks (`int(block[6]) == 0` is false or empty), producing an empty `extracted_text = ""` and `is_empty = True`.
- No page-level classifier currently exists to distinguish digital text from scanned images.

### 4.2 Table Extraction (`app/services/financial_table_extractor.py`)
- Employs `page.find_tables(strategy="lines")` to identify ruled tables from PDF vector drawings (`page.get_drawings()`).
- Normalizes column headers, fiscal periods (`FY2025`, `FY2024`, `FY2023`), currencies (`USD`, `₹`, `€`), and unit multipliers (`thousands`, `millions`).
- Normalizes cell values via `financial_cell_normalizer.py` using `Decimal`.
- Encodes tables with marker `[FINASSIST_TABLE_V1]` and schema `FinancialTable`.
- **Current Limitation:** Scanned PDFs have no vector drawings (`len(page.get_drawings()) == 0`). Ruled lines inside rasterized page images are not detected by `find_tables(strategy="lines")`, resulting in 0 tables extracted from scanned reports.

### 4.3 Chunking & Embeddings (`app/services/text_chunker.py`, `app/services/embedding_service.py`)
- Tables with `status == "certain"` are budgeted at `<= 350` tokens and grouped into structured table units.
- Table units render human-readable financial representations for BGE-small-en-v1.5 embeddings and BM25 indexing.
- Bounded same-table expansion retrieves surrounding row groups upon query match.

### 4.4 Calculations & Verification (`app/services/structured_financial_calculation.py`, `claim_verifier.py`)
- Uses deterministic Python `Decimal` arithmetic for margins, growth, and cash flow reconciliation.
- Produces Markdown tables for multi-year queries and concise statements for single-metric calculations.
- Deduplicates citations and binds claims directly to supported document passages and pages.

---

## 5. OCR Engine Evaluation & Feasibility

### 5.1 PyMuPDF Built-in Tesseract Integration
- PyMuPDF `v1.28.2` contains compiled Tesseract OCR bindings:
  ```python
  page.get_textpage_ocr(language="eng", dpi=200, full=True, tessdata=...)
  ```
- **Local Windows Verification:**
  - Tested on Windows host using `backend\.venv\Scripts\python.exe`.
  - Supplying `tessdata="backend/tessdata"` successfully executes OCR directly on pixmaps and scanned PDF pages without requiring an external C++ Tesseract binary on Windows.
  - Returns character bounding boxes (`bbox`), word lists (`get_text("words")`), text blocks (`get_text("blocks")`), and hierarchical dictionaries (`get_text("dict")` / `get_text("rawdict")`).

### 5.2 Docker Container Tesseract Integration
- Inside Debian Linux backend container (`python:3.11-slim`), installed:
  - `tesseract-ocr` (`5.5.0-1+b1`)
  - `tesseract-ocr-eng` (`1:4.1.0-2`)
  - Standard tessdata at `/usr/share/tesseract-ocr/5/tessdata/eng.traineddata`.
- Tesseract CLI is verified executable at `/usr/bin/tesseract`.

---

## 6. Phase 3C Scope & Architectural Boundaries

1. **Page-Level Classifier**: Classifies each page as `DIGITAL_TEXT`, `IMAGE_ONLY`, `MIXED_CONTENT`, `LOW_TEXT_CONFIDENCE`, `OCR_REQUIRED`, or `OCR_UNSUPPORTED`.
2. **Bounded OCR Preprocessing**: Configurable DPI (150–300, default 200), rotation detection (0, 90, 180, 270 degrees), grayscale conversion, and maximum pixel limits (25 MP).
3. **Scanned Financial Table Reconstruction**: Grid clustering and coordinate-aligned column mapping from OCR words and bounding boxes, producing `FinancialTable` structures identical to digital tables.
4. **Confidence Policy & Uncertainty**: Preserves OCR confidence metadata, flags ambiguous or illegible figures, and abstains from calculations on uncertain inputs.
5. **No Hallucinations**: Missing or damaged figures are never fabricated or guessed via LLM.
