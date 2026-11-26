# Phase 7.5 Targeted Security and Reliability Review

Date: 2026-11-07

This review covered source configuration, authentication/session handling, authorization boundaries, upload/storage behavior, CORS/CSRF, errors/logging, migrations, dependency metadata, Git release hygiene, and backup guidance. It was not a penetration test, dynamic application security test, cloud audit, or complete software-composition analysis.

## Confirmed controls

- Argon2 password hashes, expiring issuer/audience-scoped JWTs, generic invalid-login responses, and active-user checks.
- HttpOnly browser authentication cookie plus double-submit CSRF protection for state-changing cookie requests.
- Production/staging startup rejects insecure cookies, weak/placeholder JWT secrets, wildcard/empty CORS, and non-HTTPS origins.
- Document/session ownership is checked against the authenticated user; frontend-provided user IDs are not trusted.
- Semantic retrieval applies user/document filters server-side; BM25 corpora are user-scoped.
- Upload handling uses bounded streaming, generated storage names, private paths, PDF structure/encryption/corruption checks, and cleanup/quarantine behavior.
- React renders answers and excerpts as text; no `dangerouslySetInnerHTML`, localStorage token persistence, or sessionStorage token persistence was found.
- Top-level errors are generic and reviewed logging statements do not deliberately include credentials, full passages, or private storage paths.
- Migrations are linear and the current expected head is `20261103_0005`.

## Phase 7.5 fixes

The original Git ignore rules did not exclude evaluation `.runtime` directories, cached embedding files, runtime logs/PDF uploads, root model caches, broad environment variants, private-key formats, SQLite variants, or downloaded report binaries. `.gitignore` now excludes those categories while preserving `.env.example`, evaluation reports, manifests, checksums, and source code. No local artifact was deleted.

The two official evaluation PDFs remain on disk but are excluded from the proposed Git baseline. Their URLs, sizes, hashes, and page counts remain in `source_manifest.json`, enabling checksum-verified reproduction without publishing the binaries in the repository.

The historical Phase 7.2 `results.json` and `resume_results.json` capture complete bearer tokens in recorded login response bodies. Those files were not rewritten because prior evaluation artifacts must be preserved, but they are now excluded from the proposed initial commit. Regenerate sanitized machine-readable results with token/cookie/header redaction before publishing them. The human report and test plan remain eligible for commit.

## Dependency review

- `python -m pip check`: no broken installed requirements.
- `npm audit --offline --omit=dev` and a full `npm audit --offline`: the local advisory cache reported zero known vulnerabilities across the installed lockfile graph (36 production and 231 development dependencies; optional/peer counts overlap npm's metadata categories).
- `pip-audit`, Gitleaks, TruffleHog, Semgrep, and Bandit were not installed, so no claim is made about their findings.
- Offline npm audit coverage depends on the local advisory cache and is not equivalent to a current online advisory scan.
- Python requirements use bounded compatible ranges rather than a fully hashed lock file; production builds should generate and review a reproducible lock/SBOM.

## Findings requiring staging or operator action

1. The repository has no commits; every eligible file is untracked. Create a reviewed initial commit before release.
2. Historical E2E JSON contains captured test bearer tokens and must not be published in its current form.
3. `.dockerignore` does not currently exclude all evaluation runtime/cache paths or report PDFs. It was not changed because Docker configuration is operator-controlled in this phase. Review a proposed ignore update before the next image build.
4. Live HTTPS cookie flags, reverse-proxy behavior, PostgreSQL roles, ChromaDB network isolation, and provider privacy were not dynamically tested.
5. Backup/restore has documentation but no completed staging restoration evidence.
6. No current Python vulnerability scanner or secret-scanning tool was available. A high-confidence pattern scan of proposed text files found no private-key, OpenAI, AWS, GitHub, or Slack token pattern, but that is not proof that no secret exists.
7. The login API returns a bearer token for non-browser clients. Browser code does not persist it, but deployments should confirm response bodies are excluded from logs and monitoring capture.

## Release recommendations

- Run current online SCA and secret scanning against the reviewed commit in CI.
- Generate an SBOM and pin/lock deployment dependencies with hashes where the toolchain supports it.
- Protect the default branch, require review and passing checks, and use signed release tags where practical.
- Exercise the full [staging acceptance checklist](STAGING_ACCEPTANCE.md), including two-user isolation and restore rehearsal.
- Apply rate limits at the trusted proxy/API layer for login, upload, retry, and chat endpoints.
- Keep PostgreSQL, ChromaDB, uploads, backups, and model/provider traffic on least-privilege private paths.
