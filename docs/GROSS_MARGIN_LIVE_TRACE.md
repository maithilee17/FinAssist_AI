# Gross margin: scoped live verification

## Confirmed code defect versus pending live evidence

Before this change, `financial_calculation.calculate()` returned `None` for **any
question containing a four-digit year**, before calling the input extractor.
Thus `Calculate gross profit margin for FY2025.` necessarily failed even if all
retrieved inputs were correct. The evidence verifier converted this to its generic
missing-input message and retried the same calculation three times. Generation
and claim verification were never reached.

The replacement validates that the question and evidence have one matching,
explicit reporting year. Missing, mismatched, or multiple years still abstain.
Period evidence is cited alongside the independent revenue and COGS sources;
claim verification reconstructs the result including that period and citations.

This establishes a code defect, not the contents of the live ChromaDB passages.
Those passages have not been captured in this restricted execution environment.
The new regression fixture uses representative split-cell text, not purported
live records. No reindexing is justified by the year-gate defect itself.

## Capture the actual execution path

After deploying the changed backend files, run from the project root:

```powershell
docker compose exec backend python -m app.diagnostics.calculation_trace --user-id 9defc5a9-d904-4ddc-ad53-377945d332ae --filename FinAssist_Sample_Financial_Report --question "Calculate gross profit margin for FY2025." --output /tmp/finassist-margin-trace.json
docker compose cp backend:/tmp/finassist-margin-trace.json "$env:TEMP\finassist-margin-trace.json"
```

Use a new output filename for a second capture; existing files are never
overwritten. If the filename resolves to multiple documents, specify exactly one
`--document-id UUID` instead of `--filename`. Do not remove the user filter.

This is a server-side operator diagnostic, not an unauthenticated HTTP endpoint.
It opens PostgreSQL in a read-only transaction, opens the existing Chroma
collection without creating one, and scopes every document read to the specified
owner/document. It executes the production RAG service without the chat router,
so it writes no messages. Unexpected model generation is refused. Provider
settings and `.env` are unchanged. Only the named output file is written; do not
commit it or publish its contents outside this investigation.

The JSON contains:

- Every selected document's Chroma record, exact text, and source metadata.
- Chroma/PostgreSQL text, page, filename, and chunk-ID comparisons.
- Fresh extraction/chunking comparisons with the original private PDF, without
  replacing stored pages, chunks, or vectors.
- Each hybrid attempt's actual fused passages and component ranking IDs.
- Exact verifier/parser input text, hashes, ownership checks, recognized inputs,
  rejected labels, period rejection reason, arithmetic proof, and citations.
- The final result of production evidence and claim verification.

`retrieval_equals_verifier` must be true for calculations: page refinement has
an explicit calculation bypass. `parser_called` is false if ownership/source
validation prevented extraction. When true, `parser_passages` identifies the
exact text supplied to the calculator. Out-of-scope records are redacted before
serializing any contents or filenames.

Do not claim live success until the captured production path shows both
850000 USD revenue and 510000 USD COGS, valid source IDs, matching FY2025 evidence,
40.00%, verified claims and supporting citations. Also retest the same question
in the authenticated GUI with only this document selected.

## Interpret staleness before considering reindexing

If both fresh-PDF comparisons are true and every Chroma record matches
PostgreSQL, reindexing cannot fix the year gate and is unnecessary.

If pages match but chunks differ, first compare the configured chunk size and
overlap. A changed chunking configuration also changes deterministic IDs; a
difference alone does not prove a damaged upload.

If fresh extraction contains required figures that stored pages/chunks omit, or
Chroma differs from the relational source, preserve the trace and original PDF.
Do not use `/{document_id}/retry` to refresh a completed report: it accepts only
failed documents and reuses existing chunks when they exist.

A non-destructive, document-specific refresh is to upload that same original PDF
as a new version under the same authenticated account. Keep the original
document, vectors, and chats intact. Verify the new version's pages, chunk text,
index count, and source metadata, then select **only its new document UUID** for
the diagnostic and GUI calculation. Retain the old version so historical source
IDs remain available. This requires no collection reset, volume deletion, user
change, or history change. Perform it only after the trace establishes a need.
