# Phase 3B baseline

Date: 2026-11-21. Read phase2_pdf_verification.md, phase3a_retrieval_financial_reasoning.md and phase3a_final_acceptance.md before application edits.

Historical acceptance: 355 backend passed / 3 skipped, 3 frontend passed, three PDFs / 11 pages / 7 chunks and restart persistence were reported for Phase 3A. These are historical claims, not a current database audit. The acceptance report also contains conflicting Chroma version labels (1.5.9 in its prose versus 0.5.2 in one topology row); the current Compose file specifies 1.5.9.

Working tree: all project files untracked on unborn main; no initial commit. Phase 3B branch creation was attempted but .git/HEAD.lock was denied. No reset/stash/staging/forced Git changes were used; unrelated work remains intact.

Current executed regression command (backend cwd):
`python -m pytest tests -m "not anyio and not asyncio" --ignore=tests/test_migrations.py -q --junitxml=../reports/phase3b_baseline_tests.xml`
Result: **260 passed, 2 skipped, 95 deselected, 2.40 s**. This is the synchronous/offline subset, not the full historical 355-pass suite. Full and representative async execution are attempted separately with bounds.

Environment: PyMuPDF 1.28.2 exposes Page.find_tables. Existing PyMuPDF dependency >=1.24 already supports the preferred detector. No pdfplumber or OCR dependency is justified for the initial ruled-table fixtures. Docker API access is denied; live services cannot be audited or mutated from this session.

Original pipeline: sorted PyMuPDF text blocks -> NFC/whitespace cleaning -> paragraphs -> estimated 500-token chunks with 100-token overlap. Chunk IDs are UUID5(document UUID, chunk index, pages, SHA256 text). Document pages already have JSON extraction_metadata. Chunk text and page lists are stored relationally; identical text plus user/document/filename/page/chunk metadata is indexed in Chroma. Retrieval retains mandatory owner/document filtering and RRF; calculators read labelled source text with Decimal and independently checked citations.

Before modifying extraction, recorded source SHA256s and five-sample extraction/chunking timings for the three existing local PDFs and a new hand-authored three-year table fixture in phase3b_baseline.json. Generated development fixtures contain no private data. No existing uploaded PDF, relational row, vector, user, chat, volume, model, or .env was modified. Existing live indexes will not be backfilled by tests or startup.

Storage decision: use the existing page JSON metadata plus a versioned, bounded structured-table chunk representation inside the existing chunk-text contract. No schema migration is planned or applied. Any later production index refresh must be separately authorized, document-specific, resumable and non-destructive to historical sources.

Final execution is recorded in phase3b_structured_table_extraction.md: 319 backend passes, one inaccessible-Chroma skip, 96 async tests deselected; a separate full-suite attempt, async health module and isolated migration test were blocked by Windows socket/event-loop permissions. The cached real BGE integration was enabled for the final subset. No live persistence success is inferred.
