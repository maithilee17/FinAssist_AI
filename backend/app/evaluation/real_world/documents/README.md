# Evaluation documents

This directory contains the exact public filings used by the Phase 7.1 evaluation.
Their official URLs, byte sizes, SHA-256 hashes, and PDF page counts are recorded in
`../source_manifest.json`. The runner refuses to continue if a local file differs from
the manifest.

The PDFs are evaluation inputs, not application fixtures and not private user uploads.
Re-download them from the manifest URLs when the binary files are not present.
