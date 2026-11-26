# Known Limitations

- OCR is not implemented. Image-only or scanned reports can produce empty extracted text.
- Tables are preserved as extracted text where possible, but complex layouts may lose row/column relationships.
- Citation cards show document names, page numbers, and excerpts; there is no authenticated in-browser PDF viewer or download endpoint.
- Evidence confidence is deterministic and explainable but not statistically calibrated.
- Evidence and claim verification reduce unsupported output; they do not guarantee correctness or eliminate hallucinations.
- Financial calculations are not yet a complete unit-aware calculation subsystem.
- Synchronous upload processing can take a long time for large reports and can tie up a request worker.
- BM25 caches are process-local. Multi-worker deployments maintain separate caches and invalidate only within each worker.
- Current laptop: live Docker/Ollama access is blocked by managed permissions. Prior laptop observations do not verify this deployment; authenticated live PDF-to-answer acceptance is outstanding.
- Phase 7.4 browser checks covered the landing and authentication surfaces only. Authenticated document/chat browser checks remained blocked by unavailable backend dependencies.
- The managed Windows test environment can stall while creating asyncio socket pairs and while running the migration test; these checks must be repeated in the developer's unrestricted environment.
- The current Git `main` branch has no commits and all project files are untracked. Establish a reviewed baseline commit before producing a release artifact.
