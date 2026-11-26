# Safe Initial Git Baseline

## Current state

The `main` branch has no commits. All eligible project files are untracked and the index is empty. Phase 7.5 did not stage or commit anything.

The proposed initial baseline is enumerated exactly in [`PROPOSED_INITIAL_COMMIT_FILES.txt`](PROPOSED_INITIAL_COMMIT_FILES.txt). Regenerate and compare that list immediately before approval because any new file changes the proposal.

## Excluded local data

`.gitignore` excludes:

- `.env` and environment variants while explicitly retaining `.env.example`;
- private key/certificate containers;
- Python/Node caches, virtual environments, build output, coverage, and editor files;
- database, SQLite, log, partial-upload, and runtime files;
- private uploads, PostgreSQL/Chroma data, and model caches;
- evaluation `.runtime` directories and reproducible embedding caches;
- downloaded official report PDFs (the source manifest retains URLs and SHA-256 hashes);
- historical Phase 7.2 machine-readable results containing captured test bearer tokens.

No excluded file was deleted. The historical E2E JSON must be regenerated with redaction before it is ever published.

## Pre-stage verification

From the repository root:

```powershell
git status --short
git ls-files --others --exclude-standard
git check-ignore -v -- .env backend/.venv backend/.model-cache `
  backend/app/evaluation/end_to_end/.runtime/finassist-e2e.db `
  backend/app/evaluation/real_world/.cache/71000000-0000-0000-0000-000000000001.embeddings.npz `
  backend/app/evaluation/real_world/documents/nvidia-2025-annual-report.pdf `
  backend/app/evaluation/end_to_end/results.json
```

Confirm `.env.example` contains placeholders only. Review all files named by `git ls-files --others --exclude-standard`. Run an approved secret scanner in addition to the bounded pattern scan documented in the Phase 7.5 security review.

## Proposed staging commands

Run these only after reviewing the manifest and approving the initial baseline:

```powershell
git add --dry-run --all
git add --all
git status --short
git diff --cached --name-status
git diff --cached --stat
git diff --cached --check
```

Before committing, verify no staged path matches any of these categories:

```powershell
git diff --cached --name-only | Where-Object { $_ -ne '.env.example' } | Select-String -Pattern `
  '(^|/)\.env($|\.)|\.pem$|\.key$|\.p12$|\.pfx$|\.db$|\.sqlite3?$|(^|/)uploads/|(^|/)\.runtime/|(^|/)\.cache/|(^|/)\.model-cache/|node_modules/|frontend/dist/|documents/.*\.pdf$|end_to_end/(results|resume_results)\.json$'
```

Expected result: no output. If anything appears, unstage it with `git restore --staged -- <path>` and update the ignore rules before continuing.

`git add --dry-run --all` still takes an index lock. The managed Phase 7.5 workspace exposes `.git` read-only, so that dry-run could not execute here; run it locally before approval.

## Proposed commit

No commit is authorized by this document. After the user approves the staged diff:

```powershell
git commit -m "feat: establish FinAssist AI release baseline"
git show --stat --oneline --decorate HEAD
git status --short
```

Expected final state: the commit shows only the reviewed manifest and `git status --short` is empty. Tagging, pushing, and branch-protection configuration are separate explicit actions.
