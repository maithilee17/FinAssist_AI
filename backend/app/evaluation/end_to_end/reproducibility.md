# Phase 7.2 Reproducibility

Run commands from PowerShell. The commands below intentionally use an isolated SQLite database because PostgreSQL was unavailable in the evaluated environment. This does not validate PostgreSQL-specific behavior.

## Inputs

The official PDFs are already validated in `backend/app/evaluation/real_world/documents/`:

- `nvidia-2025-annual-report.pdf` — SHA-256 `757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc`
- `coca-cola-2024-10-k.pdf` — SHA-256 `96da013cf58c651ae82253c926bfe5bbd1ae63fbcdd4da03efaecf363da11963`

## Configure the isolated backend

```powershell
cd backend
$env:DATABASE_URL = 'sqlite+aiosqlite:///./app/evaluation/end_to_end/.runtime/finassist-e2e.db'
$env:JWT_SECRET_KEY = 'replace-with-one-stable-local-test-secret-at-least-32-characters'
$env:CHROMA_HOST = '127.0.0.1'
$env:CHROMA_PORT = '8001'
$env:UPLOAD_DIR = './app/evaluation/end_to_end/.runtime/uploads'
$env:HF_HOME = (Resolve-Path '.model-cache').Path
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:LLM_PROVIDER = 'ollama'
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
$env:CORS_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep the same `JWT_SECRET_KEY` across restart tests.

## Start the frontend

In a second PowerShell window:

```powershell
cd frontend
$env:VITE_API_URL = 'http://127.0.0.1:8000/api'
$env:VITE_CSRF_COOKIE_NAME = 'finassist_csrf_token'
$env:VITE_MAX_UPLOAD_SIZE_MB = '50'
npm run dev -- --host 127.0.0.1
```

## Full fresh evaluation

This is expensive: it uploads both reports and computes real BGE embeddings on CPU before the unavailable Chroma boundary.

```powershell
cd backend
$env:FINASSIST_E2E_PASSWORD = 'choose-a-strong-local-test-password'
.\.venv\Scripts\python.exe app\evaluation\end_to_end\runner.py
```

## Resume without duplicate uploads

Use this only after `runner.py` and the browser Coca-Cola upload have persisted their records:

```powershell
cd backend
$env:FINASSIST_E2E_PASSWORD = 'the-same-local-test-password'
.\.venv\Scripts\python.exe app\evaluation\end_to_end\resume_checks.py
.\.venv\Scripts\python.exe app\evaluation\end_to_end\finalize_results.py
```

## Automated verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m ruff check app tests
$env:DATABASE_URL = 'sqlite+aiosqlite:///./app/evaluation/end_to_end/.runtime/finassist-e2e.db'
.\.venv\Scripts\python.exe -m alembic current

cd ..\frontend
npm run lint
npm run build
```

## Optional integrations

The two skipped backend tests require explicit opt-in and running services:

```powershell
$env:RUN_CHROMA_INTEGRATION = '1'
$env:RUN_LLM_INTEGRATION = '1'
```

Do not enable `RUN_LLM_INTEGRATION` unless a non-paid local provider is deliberately configured. This evaluation did not run either integration.

