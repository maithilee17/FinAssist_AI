# FinAssist AI — 5-Minute Portfolio Interview Demo Guide

**Target Audience:** Technical Recruiters, Hiring Managers, Senior AI Engineers, and Staff Software Engineers.  
**Demonstration Time:** ~5 minutes  
**Repository:** `FinAssist AI` (Full-Stack RAG Financial Intelligence Application)

---

## 1. High-Level Elevator Pitch (30 Seconds)

> *"FinAssist AI is a production-grade Financial Document Intelligence and RAG platform. In finance, generic LLMs fail because they hallucinate numbers, misread scale multipliers like 'USD in thousands', confuse percentage points with growth percentages, and cannot handle scanned tables. FinAssist AI solves this with a multi-layered pipeline: hybrid BM25 and BGE semantic retrieval with reciprocal rank fusion (RRF), deterministic Decimal financial calculation engines, Tesseract OCR for scanned financial statements, strict evidence verification with citation grounding, and an executive financial dashboard."*

---

## 2. Technical Architecture & Tech Stack (45 Seconds)

Point to the architecture:
- **Backend:** FastAPI (Python 3.11), SQLAlchemy Async ORM, Alembic migrations, Pydantic v2.
- **Frontend:** React 19 + Vite, Tailwind CSS, Accessible HTML Tables, Native SVG charts (zero bloated heavy-chart dependencies).
- **Databases:** PostgreSQL (ACID relational document metadata & user auth), ChromaDB (Vector embeddings).
- **Retrieval & RAG:** BGE-small-en-v1.5 embeddings, BM25 keyword index, Reciprocal Rank Fusion, Deterministic Evidence Verifier.
- **Financial Calculation:** Deterministic Python `Decimal` arithmetic engine with zero LLM math hallucinations.
- **OCR:** PyMuPDF layout analysis and Tesseract OCR for physical/scanned statement reconstruction.
- **LLM:** Ollama with `qwen3:4b-instruct` / `qwen2.5:7b` (local, privacy-preserving financial data processing).
- **DevOps:** Docker Compose, automated health checks, multi-stage production builds.

---

## 3. Live 5-Minute Walkthrough Script

### Step 1: Health & Startup Verification (30 Seconds)
1. Show the running containers via terminal or PowerShell:
   ```powershell
   docker compose ps
   ```
2. Point out that all 4 microservices (`backend`, `frontend`, `postgres`, `chroma`) are up and passing automated health checks.
3. Open `http://localhost:5173/` in Google Chrome.

### Step 2: Document Ingestion & Multi-Year Table Extraction (1 Minute)
1. Log into `http://localhost:5173/login` using `phase3e-browser@example.com` (or create a new user to show multi-tenancy).
2. Go to Document Management (`/documents`).
3. Show uploaded documents:
   - `three_year.pdf` (Multi-year digital report covering FY2023, FY2024, FY2025).
4. **Key Talking Point:** Explain how the system extracts tables:
   - PyMuPDF reads table blocks without mangling columns.
   - Header paths identify instant vs. duration periods (`FY2025`, `FY2024`, `FY2023`).
   - Units and scale multipliers (`USD in thousands`, `millions`) are normalized automatically.

### Step 3: Evidence-Grounded Financial Question Answering (1.5 Minutes)
1. Click **Chat** in the navigation bar (`/chat`).
2. Ask the core financial question:
   > *"Calculate the gross profit margin for Example Industries in FY2025."*
3. Observe the response:
   - The answer computes: `gross profit margin: 420000 / 1200000 * 100 = 35.00% [Source 1]`.
   - **Show the Verification Badges:**
     - `Hybrid retrieval · 2 passages`
     - `Verified · sufficient evidence · high evidence confidence`
     - Expandable evidence cards showing the exact page and table source.
4. **Interview Talking Point:**
   - Highlight that the LLM is **never allowed to do raw math**. The formula and Decimal inputs are extracted and executed deterministically via the backend calculation engine, eliminating hallucination risks.

### Step 4: Executive Financial Dashboard (1.5 Minutes)
1. Click **Dashboard** in the navigation bar (`/dashboard`).
2. Select `three_year.pdf` from the dropdown.
3. Point out the **Key Performance Indicators (FY2025)**:
   - **Total Revenue:** `$1.20M` (`+26.32% YoY`)
   - **Gross Profit:** `$420K` (`+31.25% YoY`)
   - **Gross Margin:** `35.00%` (`+1.32 pp`)
     - **CRITICAL DEMO DETAIL:** Highlight the `+1.32 pp` badge. Explain why labeled as `pp` (percentage points) rather than `% YoY`:
       $$\Delta = 35.00\% - 33.68\% = +1.32\text{ percentage points}$$
       $$\text{Relative YoY growth would have been } \frac{35.00 - 33.68}{33.68} = +3.92\%$$
       This demonstrates financial acumen and attention to detail.
   - **Net Income:** `$91K` (`+16.67% YoY`)
4. Point out the **Longitudinal Trend Charts**:
   - Revenue Trend bar chart.
   - Profitability Breakdown grouped bars.
   - Profit Margin Trend dual-line chart.
5. Point out the **AI Financial Performance Summary**:
   - Synthesizes multi-year expansion dynamics grounded in verified table citations.

---

## 4. Key Questions & Strong Answers for Placement Interviews

### Q1: "How do you prevent financial hallucinations in RAG?"
> *"We implement a zero-trust evidence architecture. First, retrieval uses hybrid search (BM25 + BGE embeddings) fused via Reciprocal Rank Fusion. Second, an Evidence Verifier inspects whether the retrieved passage contains the exact metric, reporting period, and co-occurring numerical figures. If evidence is insufficient, the system safely abstains rather than guessing. Finally, calculations are parsed into deterministic Decimal expressions and verified against citation bounds."*

### Q2: "How do you handle scanned or physical financial PDFs?"
> *"We built an OCR pipeline using Tesseract OCR. When PyMuPDF detects an image-only page, our OCR engine extracts word tokens and bounding boxes, applies heuristic column clustering, handles accounting parentheses (e.g. `(90,000)` parsed as negative `-90000`), and reconstructs structured tabular data with explicit unit multipliers."*

### Q3: "How is multi-tenancy secured?"
> *"Every database query and vector retrieval operation requires the authenticated `user_id` extracted from a signed JWT. If User B attempts to access a document owned by User A, the service returns HTTP 404 rather than 403, preventing document ID enumeration attacks. Uploads are strictly validated with magic-byte inspection."*

---

## 5. Quick Verification Commands for Interviewers

```powershell
# 1. Run all backend tests (445 tests passed)
$env:PYTHONPATH = "backend"; & "backend\.venv\Scripts\python.exe" scripts/run_all_backend_tests.py

# 2. Run frontend unit tests (14 tests passed)
cd frontend; npm test

# 3. Run real-world financial evaluation against Coca-Cola & NVIDIA filings
$env:PYTHONPATH = "backend"; & "backend\.venv\Scripts\python.exe" scripts/evaluate_real_financial_pdfs.py

# 4. Live API verification
& "backend\.venv\Scripts\python.exe" scripts/verify_phase3d_live.py
```
