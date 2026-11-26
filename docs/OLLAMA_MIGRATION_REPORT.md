# Ollama-only implementation report — 2026-11-16

## Scope and starting state

Read `PROJECT_AUDIT_2026-11-10.md` before changes. It is the available project
audit; no separately named Task 1 report was found under docs. Re-inspected the
actual settings, requirements, LLM adapter/factory, RAG dependencies and pipeline,
chat/error/history routes, health routes, Compose, entrypoint, startup scripts,
frontend requests, tests, and operational documentation.

The supplied source already had an Ollama-only implementation: no Gemini SDK,
Gemini adapter, Gemini key requirement, or cloud provider branch remained.
Consequently no runtime files or dependencies needed deletion. The rejection test
containing the word `gemini` deliberately verifies that unsupported configuration
fails; it is not a Gemini integration. Historical evaluation reports and secret
redaction names remain historical/security records, not supported providers.

There is no tracked source baseline (the project files are untracked), so this is
a report of this session's edits, not a claim that all existing Ollama code was
implemented in this session.

## Architecture and preservation

- `Settings.llm_provider` accepts only `ollama`; the factory also fails closed.
- Native URL: `http://localhost:11434`; Compose overrides it with
  `OLLAMA_DOCKER_BASE_URL`, default `http://host.docker.internal:11434`.
- Existing httpx `/api/chat` adapter sends separate system/evidence messages,
  disables streaming, sets temperature zero, and limits context/output tokens.
- Connect/generation timeouts, unavailable services, missing models, server errors,
  malformed text, and invalid token usage map to safe application errors. Chat
  maps timeout to 504 and service/missing-model errors to 503.
- Added rejection of explicitly incomplete non-streaming responses and malformed
  model inventory entries. No raw provider response body is returned to clients.
- Usage is taken from Ollama `prompt_eval_count` / `eval_count`; no cloud cost is
  invented. Readiness checks the selected installed model; liveness stays independent.
- Existing BM25/BGE/Chroma retrieval, ownership filters, evidence sufficiency,
  prompt delimiters, citation/claim checks, abstention, authentication, and history
  persistence remain in place.
- No changes to BGE model/revision/dimension, Chroma collection, database schema,
  migrations, uploaded documents, local embeddings, users, chats, or volumes.
- `.env` was not edited, replaced, or printed. No packages were installed, no
  models downloaded, no containers started, and no migrations executed by us.

## Hardware and model decision

Measured on this laptop, not copied from prior memories:

| Resource | Observation |
| --- | --- |
| CPU | AMD Ryzen 9 8940HX with Radeon Graphics (Windows registry) |
| Usable physical RAM | 23.05 GiB (`GlobalMemoryStatusEx`) |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU |
| VRAM | 8,151 MiB (`nvidia-smi`) |
| NVIDIA driver | 592.82 |

CIM access was unavailable, so registry and the Windows memory API supplied CPU
and RAM information. Recommend keeping **qwen2.5:7b** as the primary candidate and
**qwen2.5:3b** as an optional, manually selected fallback. No automatic fallback.

| Criterion | Primary 7B candidate | Optional 3B candidate |
| --- | --- | --- |
| Downloaded Q4_K_M weights | About 4.7 GB | About 1.9 GB |
| Financial text and tables | Family documents structured-data understanding; verify on the project's report cases | Same family, less capacity; accept only after the same tests |
| Numerical reasoning | Family documents math improvements; arithmetic and units still require evidence checks | Greater capacity tradeoff; do not assume equal numerical reliability |
| Instructions / structured output | Family documents instruction following and JSON capability; current app uses cited prose | Same interface, lower-capacity option |
| Hallucination resistance | No verified model-specific guarantee; retain RAG abstention and claim checks | Same safeguards required |
| Latency | Unmeasured on this host | Expected lower resource use; latency advantage is an inference, not a benchmark |
| Memory | Plausible for 8 GB VRAM at the configured 8K context; KV cache/runtime/display add overhead | More VRAM headroom; useful if primary offloads or times out |

This is a hardware-informed candidate recommendation, not an empirical quality
ranking or a claim of full GPU residency. After approved installation, check
`ollama ps`, `nvidia-smi`, response timing, and the fictional PDF acceptance cases
in the audit. Verify revenue, period comparisons, units, citations, absent metrics,
and prompt-injection resistance. Record cold/warm latency and peak memory.

Official references inspected on 2026-11-16:

- https://ollama.com/library/qwen2.5:7b
- https://ollama.com/library/qwen2.5:3b
- https://docs.ollama.com/faq

## Windows setup and operation

Install Docker Desktop with a working Linux container engine, and Ollama for
Windows. Python 3.11 and Node are needed only for native development/testing;
Compose builds use their Dockerfiles. Git Bash is needed only for the older Bash
launcher. The new PowerShell launcher does not require Git Bash or a WSL shell.

Create `.env` only if absent, then edit its secrets yourself:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Keep `LLM_PROVIDER=ollama`, choose the model explicitly, and leave BGE settings
unchanged. Set `OLLAMA_NO_CLOUD=1` in the Windows Ollama server environment and
restart Ollama to disable cloud features; the backend rejects cloud model names
and the Ollama cloud endpoint as an additional configuration guard.

Model downloads require approval. Only after approval, run one of:

```powershell
ollama pull qwen2.5:7b
# Optional manual fallback only:
ollama pull qwen2.5:3b
```

No model is downloaded by the application or launchers. Start Ollama yourself and
verify `Invoke-RestMethod http://localhost:11434/api/tags`. Build and start after
environment changes are approved:

```powershell
docker compose build backend frontend
powershell -ExecutionPolicy Bypass -File .\start-finassist.ps1
```

The launcher validates Compose without printing resolved secrets, checks Docker,
uses a transient backend container to verify the actual container-to-host path and
model without migrations/generation, then starts Compose with bounded health waits.
Compose waits for PostgreSQL and Chroma before backend startup. The existing
backend command applies pending Alembic upgrades before Uvicorn. This has not been
executed during this migration. Missing Ollama does not prevent access to existing
accounts/documents via manual Compose startup, but readiness is 503 and generation
fails clearly. The launcher requires Ollama readiness before starting the stack.

Default URLs: frontend http://localhost:5173, API docs http://localhost:8000/docs,
liveness http://localhost:8000/api/health/live, readiness
http://localhost:8000/api/health/ready, Chroma heartbeat
http://localhost:8001/api/v2/heartbeat. The PowerShell launcher reads configured
published frontend/backend ports from Compose.

```powershell
docker compose exec backend python -m app.diagnostics.ollama
# Separate real generation diagnostic, only when explicitly wanted:
docker compose exec backend python -m app.diagnostics.ollama --generate
```

The first checks tags/model availability without generation or downloads; the
second adds generation and prints only answer length/token counts. It proves
generation returned usable text, not financial accuracy or end-to-end RAG quality.

Separate opt-in real inference test (from a fresh backend environment):

```powershell
$env:RUN_OLLAMA_INTEGRATION='1'
python -m pytest tests/test_phase4_integrations.py::test_real_ollama_generation_returns_text -q
Remove-Item Env:RUN_OLLAMA_INTEGRATION
```

Normal tests use mocks. Do not enable Chroma integration against production data.

Troubleshooting:

- If the host API fails, start Ollama and check its logs before changing network settings.
- If only the container path fails, run the diagnostic inside the backend. Use
  `host.docker.internal`, never a laptop-specific IP. If a bind/firewall change is
  needed, make it explicitly and restrict access to Docker/private traffic.
- Missing models: approve a host-side pull or select an already installed local model.
- Timeout: inspect cold loading, GPU residency, context size, and competing VRAM
  users. The browser now waits 360 seconds, beyond the backend's allowed 300-second
  generation timeout. Do not assume raising timeouts fixes insufficient memory.
- Copied virtual environment: its executable points to the old laptop's Python.
  Create a fresh environment at a new path; do not delete model caches or uploads.
- Docker pipe permission denied: verify Docker Desktop access in an authorized
  terminal. We did not modify permissions, restart Docker, or attempt escalation.

Safe shutdown: `docker compose stop`. Preserve all named volumes and private files;
never use `down -v`, pruning, collection resets, or migration resets for repairs.

## Files changed by this session

| File | Change |
| --- | --- |
| `.env.example` | Primary and optional manual fallback comments; no secrets |
| `README.md` | Ollama-only architecture, PowerShell start, cloud-disable guidance, readiness correction |
| `docs/ENVIRONMENT_CONFIGURATION.md` | Removed obsolete cloud switching/key instructions; consistent native/Docker URLs and models |
| `backend/app/services/llm_service.py` | Incomplete output and inventory validation; typed validation failures |
| `backend/tests/test_llm_service.py` | Added incomplete-output and malformed-inventory regressions; formatting |
| `backend/tests/test_chat_api.py` | Added timeout/missing-model/connection HTTP mapping and no-new-history regressions; import formatting |
| `backend/tests/test_phase4_integrations.py` | Real Ollama test also checks supplied numeric fact; import formatting |
| `backend/tests/conftest.py`, `test_health.py`, `test_migrations.py` | Import ordering only for current Ruff |
| `frontend/src/pages/ChatPage.jsx` | Allow backend timeout diagnostic to reach browser |
| `backend/app/diagnostics/ollama.py` (new) | Model readiness and opt-in generation diagnostic |
| `start-finassist.ps1` (new) | Native Windows preflight and safe Compose startup |
| `docs/OLLAMA_MIGRATION_REPORT.md` (new) | This report |

Files removed: **none**. Dependencies removed: **none**, because provider SDKs
were already absent. Compose, Dockerfiles, embeddings, and Alembic migrations did
not require source changes.

## Validation and limitations

| Check | Result |
| --- | --- |
| Selected backend synchronous regression suite | 61 passed, 0 failed |
| Provider/factory/default/unsupported-provider pytest cases | 6 passed, 0 failed |
| Supplemental inline mock adapter checks | 11 passed; no event loop/network; not counted as pytest passes |
| Full backend async suite | Blocked before async execution by Windows socketpair/event-loop initialization hang; interrupted |
| Ruff `app tests` | Passed |
| Formatting of 8 touched backend files | Passed |
| Frontend unit tests | 3 passed, 0 failed |
| Frontend ESLint | Passed |
| Frontend production build | Passed, 1,760 modules |
| PowerShell launcher syntax | Passed |
| Compose config (`--quiet`) | Passed; resolved secrets were not printed |
| Docker engine/build/runtime/container-host connection | Blocked: engine named-pipe permission denied |
| Host Ollama `/api/tags` | Unreachable |
| Real generation / browser RAG acceptance | Not verified; no successful live generation |

Full async tests cannot be claimed passed. A bounded faulthandler probe located
the hang in Python's Windows proactor event-loop creation (`socket.socketpair`
accept), before the mock adapter test body. No application workaround or global
event-loop policy was added for this restricted execution host. Async auth,
upload, chat, health and RAG tests must be rerun in a working local environment.
The supplemental inline checks cover successful parsing/token usage, incomplete
and malformed output, HTTP errors, missing models, connect failures, timeouts,
and malformed/readable model inventories without scheduling real I/O.

No deployment-ready or live financial-answer-quality claim is made. Remaining
acceptance requires an approved working Python environment, Docker access,
running Ollama with an approved installed model, the full mock suite, live Docker
readiness/connectivity, and upload-to-answer/browser checks from the original
audit. No further environment-changing action was taken.
