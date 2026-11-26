# Phase 7.5 Release-Readiness Verification

Date: 2026-11-07

## Outcome

Release-readiness documentation, Git hygiene, artifact redaction, placement materials, and locally executable checks are complete. Production acceptance is not complete: PostgreSQL, ChromaDB, HTTPS, secure-cookie transport, full browser E2E, backup restoration, and an authorized LLM provider remain blocked or not run.

No Docker command, container action, paid API call, Ollama request, Git staging, or Git commit was performed.

## Git baseline

- `main` has no commits and the index is empty.
- The final manifest contains 162 eligible untracked files after new ignore rules removed runtime/private/generated artifacts.
- Evaluation runtime logs/uploads, SQLite data, embedding caches, model caches, downloaded report PDFs, and token-bearing historical E2E JSON are excluded.
- Official report URLs, byte sizes, page counts, and SHA-256 hashes remain in the committed source manifest.
- The exact final proposal is in `PROPOSED_INITIAL_COMMIT_FILES.txt`; no commit is authorized automatically.
- `git add --dry-run --all` was blocked because the managed workspace exposes `.git` read-only and Git could not create `index.lock`. No staging occurred; the user must run the dry-run locally.

## Confirmed security defect and fix

Historical Phase 7.2 `results.json` and `resume_results.json` contain complete bearer tokens captured from login responses. The historical files were preserved and excluded from Git. Future E2E serialization now recursively redacts sensitive keys, JWT-shaped strings, and FinAssist cookie values. Two deterministic regression tests cover nested fields and values embedded in header strings.

## Dependency review

- Python `pip check`: passed; no broken installed requirements.
- Frontend production-only and full `npm audit --offline`: local advisory cache reported 0 vulnerabilities across the installed lockfile graph (36 production and 231 development dependencies).
- `npm ls --depth=0`: passed.
- `pip-audit`, Gitleaks, TruffleHog, Semgrep, and Bandit: unavailable.
- Bounded high-confidence secret-pattern scan of eligible text files: no private-key, OpenAI, AWS, GitHub, or Slack token signature found. One deliberately JWT-shaped string exists in the redaction regression test and contains only synthetic fixture data.

Offline npm results are only as current as the local cache. The bounded pattern scan is not a replacement for a dedicated secret scanner.

## Automated verification

### Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\python.exe -m pytest -m "not anyio" --ignore tests/test_migrations.py -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format --check `
  app\evaluation\end_to_end\runner.py `
  app\evaluation\end_to_end\resume_checks.py `
  tests\test_e2e_artifact_redaction.py `
  app\config.py app\main.py tests\test_config.py
```

Results:

- 110 tests collected.
- Bounded service-independent selection: **53 passed, 0 failed, 1 skipped, 55 deselected** in 1.65 seconds.
- The skip is the opt-in live ChromaDB test.
- The 55 async-marked tests and one migration test were not executed in this bounded selection because the managed Windows environment previously stalled in asyncio socket-pair and migration paths.
- Ruff lint: passed.
- Phase 7.4/7.5 changed Python files: formatter check passed.
- Repository-wide formatting still identifies the pre-existing Phase 7.3 performance runner; it remains untouched.

### Frontend

```powershell
cd frontend
npm run lint
npm run build
```

- ESLint: passed.
- Vite production build: passed; 1,759 modules transformed in 9.90 seconds.
- JavaScript: 376.57 kB (119.55 kB gzip).
- CSS: 37.32 kB (7.13 kB gzip).
- No browser automation framework is installed. No authenticated staging browser flow ran in Phase 7.5.

## Deliverables

- Architecture and trust/data-flow explanation.
- Safe initial Git baseline and exact proposed file manifest.
- Staging acceptance checklist with explicit evidence categories.
- Twelve-case browser E2E plan including two-user isolation and accessibility.
- Operations, metrics, logging, backup, and restoration guidance.
- Targeted security/reliability review.
- Placement pitch, honest evaluation story, demo script, resume bullets, and interview answers.
- Professional README status/results/roadmap updates.

## Blocked and not run

- PostgreSQL connection, migrations, roles, backup, and restoration.
- Live ChromaDB health, indexing, filtering, deletion, latency, and isolation.
- HTTPS reverse proxy, secure-cookie transport, CSRF/CORS browser behavior.
- Authorized OpenAI/Ollama generation, answer quality, latency, usage, and cost.
- Full authenticated browser E2E and screen-reader testing.
- Full async pytest group and migration test in this managed Windows environment.
- Current online Python/Node vulnerability databases and dedicated secret scanning.
- Production load, failure recovery, and alert delivery.

## Preservation

Phase 7.1–7.4 reports and benchmark measurements were not rewritten. Historical token-bearing Phase 7.2 JSON remains on disk but is intentionally ignored until sanitized regeneration is performed.
