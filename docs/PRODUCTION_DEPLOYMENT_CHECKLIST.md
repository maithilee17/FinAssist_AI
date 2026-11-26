# Production Deployment Checklist

## Before release

- [ ] Create and review the repository's initial commit; the current `main` branch has no commits and all project files are untracked.
- [ ] Review and apply every Alembic migration against a backed-up staging database.
- [ ] Set `APP_ENV=production`, a unique strong `JWT_SECRET_KEY`, and `COOKIE_SECURE=true`.
- [ ] Configure exact HTTPS `CORS_ORIGINS` and the matching `VITE_API_URL`.
- [ ] Confirm TLS termination, forwarded headers, request-size limits, and timeouts at the reverse proxy.
- [ ] Restrict API documentation endpoints at the network layer if they are not intended for public access.
- [ ] Provision private persistent PDF storage with least-privilege permissions and sufficient capacity.
- [ ] Keep PostgreSQL and ChromaDB on private networks with authentication, backup, and monitoring appropriate to the deployment.
- [ ] Pin Python, Node, embedding-model, and provider-model versions.
- [ ] Supply secrets through the hosting platform's secret manager; verify none are present in frontend assets.
- [ ] Configure structured log collection without document passages, credentials, cookies, or authorization headers.

## Release verification

- [ ] `alembic current` reports the expected head revision.
- [ ] `/api/health/live` returns 200.
- [ ] `/api/health/ready` returns 200 only after PostgreSQL and ChromaDB are reachable.
- [ ] Registration, login, session reload, CSRF rejection, and logout work over HTTPS.
- [ ] Two-user ownership checks pass for documents, vectors, and chat sessions.
- [ ] A legally usable PDF completes extraction, chunking, embedding, and indexing.
- [ ] Invalid, encrypted, oversized, and corrupted files fail safely.
- [ ] Grounded answer, abstention, citation, evidence, and confidence displays match backend responses.
- [ ] Document and conversation deletion complete across every persistence layer.
- [ ] Desktop, tablet, mobile, keyboard-only, and screen-reader smoke checks pass.

## Operations

- [ ] Alert separately on liveness and dependency readiness failures.
- [ ] Monitor latency, memory, queue/request saturation, indexing failures, provider errors, and storage growth.
- [ ] Document JWT-secret rotation, database restore, vector reindexing, and provider-outage procedures.
- [ ] Test backups and restoration rather than relying only on successful backup jobs.
- [ ] Define incident-response contacts and a document-retention/deletion policy.

This checklist documents requirements only. Phase 7.4 did not start infrastructure or validate a production hosting environment.
