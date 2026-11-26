# Browser End-to-End Test Plan

## Tooling decision

The repository currently has no Playwright, Cypress, Vitest, or React Testing Library dependency. Phase 7.5 does not add a large browser-test dependency before the staging services and stable test data are available. Execute this plan manually in two isolated browser profiles first. If automation is added later, Playwright is the smallest appropriate fit because it supports multiple browser contexts, file uploads, cookie inspection, mobile viewports, accessibility locators, screenshots, and trace capture.

Use only dedicated staging users and authorized test PDFs. Never record passwords, session cookies, tokens, or private document passages in screenshots or traces.

## Preconditions

- A reviewed commit is deployed over HTTPS.
- PostgreSQL migrations are at head and ChromaDB readiness passes.
- The frontend uses the staging `VITE_API_URL` and exact allowed origin.
- Two unique staging accounts are available.
- At least one checksum-recorded annual report has approved test use.
- LLM-dependent cases run only when a provider is explicitly authorized. Retrieval and safe-failure cases can run without generation.

## Test cases

| ID | Workflow | Steps | Expected result | Current status |
| --- | --- | --- | --- | --- |
| E2E-01 | Registration and login | Register User A; try duplicate registration; sign in with wrong then correct password | Safe validation; generic invalid-login response; dashboard opens only after valid login | Blocked: staging backend unavailable |
| E2E-02 | Session persistence and logout | Reload authenticated page; open new tab; log out; revisit dashboard | Session survives reload while valid; logout clears access; protected route redirects | Blocked |
| E2E-03 | Upload | Drag an authorized PDF; observe browser validation and progress | Progress and post-upload processing state are distinct; no private path is shown | Blocked |
| E2E-04 | Processing/indexing | Poll status and inspect metadata/pages | Completed only after extraction, chunking, and vector count verification; one-based pages | Blocked by PostgreSQL/ChromaDB |
| E2E-05 | Exact value | Ask a report-specific metric/year question | Keyword/hybrid route; exact value, unit, period, evidence and real citation shown | Blocked by ChromaDB and provider |
| E2E-06 | Conceptual | Ask why a disclosed margin or risk changed | Semantic route; grounded explanation and relevant source excerpts | Blocked |
| E2E-07 | Comparison | Ask for two periods with the same metric | Hybrid route; both periods and units supported; no assumed missing value | Blocked |
| E2E-08 | Unanswerable | Ask for an absent metric or future period | Safe abstention; missing aspect explained; no invented citation | Blocked; deterministic policy unit-tested |
| E2E-09 | Evidence inspection | Expand every citation and verification panel | Filename, page, excerpt, claims, evidence state and confidence explanation match API data | Blocked |
| E2E-10 | Delete document | Delete with confirmation, refresh, query old ID | Metadata/file/vector cleanup reflected; old ID returns 404; chat does not expose file | Blocked |
| E2E-11 | Two-user isolation | In separate contexts, try User A identifiers from User B | Lists, fetches, chunks, sessions and delete operations remain isolated | Blocked |
| E2E-12 | Mobile and keyboard | Test 375 px and tablet; Tab/Shift+Tab, Enter, Escape; screen reader smoke test | No clipped controls; logical focus order; named controls; visible focus; dialogs operable | Landing/login mobile and keyboard smoke passed; authenticated screens blocked |

## Financial question fixture

Record expected values directly from the approved report and its page before the run; do not put those answers into application code. Include:

- one exact metric with currency/unit and reporting period;
- one management explanation or risk disclosure;
- one two-period comparison with consistent units;
- one question requiring at least two passages;
- one absent metric and one future/unsupported period;
- one cross-document question when both reports are indexed.

For each response capture the selected strategy, top chunk IDs, retrieval/verification timings, evidence status, attempts, claim support, returned citations, final/abstained answer, and manually reviewed correctness.

## Accessibility and responsive checklist

- Use accessible-name locators rather than CSS classes in future automation.
- Confirm labels and error messages are programmatically associated.
- Confirm status/progress updates are announced without moving focus.
- Confirm dialogs trap or manage focus appropriately and restore focus after close.
- Confirm color is not the only evidence/status signal.
- Check 200% zoom, 320/375/768/1280 widths, reduced motion, and high contrast where supported.
- Run a screen-reader smoke test on registration, documents, upload, chat, citations, and delete confirmation.

## Evidence capture

For each case record: commit SHA, environment, browser/version, viewport, timestamp, account alias, pass/fail/blocked, HTTP status, screenshot/trace path, and defect ID. Redact email addresses where practical and never capture cookies or authorization headers.
