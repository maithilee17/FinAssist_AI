# Environment Configuration

Copy `.env.example` to a private environment file outside version control. Never commit real credentials.

## Required production values

| Variable | Requirement |
| --- | --- |
| `APP_ENV` | `production` or `staging` enables strict startup validation. |
| `JWT_SECRET_KEY` | Unique random secret of at least 32 characters; rotate through the deployment secret manager. |
| `COOKIE_SECURE` | Must be `true` outside development. |
| `COOKIE_SAMESITE` | Prefer `lax` for same-site deployments; `none` also requires Secure cookies. |
| `CORS_ORIGINS` | Comma-separated explicit HTTPS frontend origins. Wildcards and HTTP origins are rejected outside development. |
| `VITE_API_URL` | Public HTTPS API base ending in `/api`; use a same-site reverse-proxy URL when practical. |
| `DATABASE_URL` | PostgreSQL async SQLAlchemy URL supplied through the secret manager. |
| `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_SSL` | Reachable private vector service settings. |
| `UPLOAD_DIR` | Private persistent storage path writable only by the backend service account. |
| `LLM_PROVIDER` | `ollama` only; other values are rejected. |

`VITE_*` variables are compiled into browser assets and must never contain secrets. Database credentials, JWT secrets, and private service addresses belong only in backend runtime configuration.

## Cookies and origins

Credentialed requests require an exact allowed origin. The browser sends an HttpOnly authentication cookie and a readable CSRF cookie; Axios mirrors the CSRF value into `X-CSRF-Token` for state-changing requests. Keep frontend and API same-site when possible. If they are cross-site, configure HTTPS, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none`, and the exact frontend origin.

## Storage

- The upload directory must not be inside the frontend build, a public static directory, or a shared web root.
- Mount persistent storage with least-privilege read/write permissions for the backend identity.
- Include uploaded PDFs, PostgreSQL, ChromaDB data, and model caches in capacity planning.
- Define backup, retention, quarantine cleanup, and secure deletion policies appropriate for the financial documents processed.

## Model and provider readiness

Cache and pin the approved BGE model artifact before production rollout. Validate the configured LLM provider in a non-production environment. FinAssist fails clearly when the provider is not configured; it does not generate a synthetic answer.

## Local Ollama on Windows with Docker Desktop

Ollama runs on the Windows host; do not install it in the backend image or add an
Ollama container. Install Ollama from its official Windows installer, then verify the
server and required lightweight model in PowerShell:

```powershell
ollama --version
ollama pull qwen2.5:7b
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Ollama normally starts its Windows service/application automatically. If it is not
running, start it with `ollama serve` in a separate PowerShell window. Do not pull the
model from inside Docker; the host installation owns the model files.

Configure the private root `.env` without changing embedding or vector settings:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DOCKER_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_CONNECT_TIMEOUT_SECONDS=5
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=800
```

No external LLM API key is used. Docker Desktop resolves
`host.docker.internal` to the Windows host; no Ollama port is published by Compose.
Keep Ollama bound to the local machine unless a narrowly scoped host-network rule is
required. Verify the path from the existing backend container without exposing other
model names:

```powershell
docker compose exec backend python -c "import httpx; r=httpx.get('http://host.docker.internal:11434/api/tags', timeout=10); print(r.status_code)"
```

Apply a provider setting change without deleting volumes:

```powershell
docker compose up -d --build backend
docker compose ps
docker compose logs --tail=100 backend
```

Ollama is the only supported provider. Select a different installed local model
with `OLLAMA_MODEL` and recreate the backend. There is no automatic fallback.

Troubleshooting:

- **Ollama is not reachable:** confirm `Invoke-RestMethod` succeeds on Windows, then
  test `host.docker.internal` from the backend as shown above. A local firewall rule,
  if needed, should be limited to Docker Desktop/WSL traffic rather than the public
  network.
- **Model is not installed:** run `ollama pull qwen2.5:7b` on Windows. FinAssist
  returns a safe message containing the configured model name and this command.
- **Request timed out:** try the optional `qwen2.5:3b` model, close memory-heavy
  applications, or increase `LLM_TIMEOUT_SECONDS` cautiously. Connection timeout and
  generation timeout are separate settings.
- **Malformed or server error:** inspect `ollama list`, the Ollama host logs, and the
  backend logs. The API does not expose raw Ollama response bodies or secrets.
