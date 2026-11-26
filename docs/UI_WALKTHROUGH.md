# FinAssist AI UI Walkthrough and User Guide

## Account access

1. Open the landing page and choose **Register**.
2. Enter a name, valid email, and a 12–128 character password using at least three character groups.
3. After registration, sign in. The browser uses an HttpOnly session cookie; FinAssist does not save the JWT in local or session storage.
4. Use **Logout** from any authenticated page to clear the session.

If a session expires, protected pages return to sign-in. Error messages intentionally avoid revealing whether an account exists.

## Dashboard

The dashboard shows actual document and conversation totals, recent documents, recent conversations, and whether one of the recently loaded documents is indexed. If the summary cannot load, an actionable error appears instead of invented counts.

## Documents

1. Open **Documents** and choose a PDF or drag one onto the upload area.
2. The browser checks extension, reported MIME type, size, and empty files. The backend remains authoritative and validates the actual PDF.
3. Upload progress reaches 100% before server extraction and indexing finish. Keep the page open until a success or error message appears.
4. Status values are **Uploaded**, **Processing**, **Indexing**, **Completed**, or **Failed**.
5. A failed document can be retried when its private original file and extracted chunks remain available.
6. Deletion permanently removes relational records and the private PDF. Vector deletion must succeed first; otherwise deletion is cancelled safely.

Encrypted PDFs and image-only reports without extractable text are not supported. Do not upload documents you are not authorized to process.

## Assistant

1. Upload and successfully index at least one PDF.
2. Choose all indexed documents or select a narrower document scope.
3. Ask a precise question. Enter sends; Shift+Enter adds a new line.
4. Each response separates the answer, retrieval route, verification result, confidence explanation, and cited evidence.
5. Expand a citation to inspect its source filename, page numbers, and retrieved excerpt.

**Verified** means the deterministic claim and citation checks found support in retrieved evidence. It does not guarantee factual certainty. **Partially supported**, **Unsupported**, and **Abstained** identify answers or portions that could not be supported. The confidence value is an evidence-quality score, not a calibrated probability.

When evidence is insufficient, refine the reporting period or metric, select the relevant document, or upload the missing report. Never treat an abstention as a zero financial value.

## Keyboard and mobile use

- All forms use explicit labels and visible focus indicators.
- Dialogs can be closed with Escape when no destructive operation is running.
- Icon-only actions have accessible names.
- The interface supports desktop, tablet, and mobile widths; side panels stack below the chat on smaller screens.
- Reduced-motion preferences disable non-essential animation.

FinAssist currently displays citation page numbers and excerpts but does not expose private PDFs through a public viewer or download URL.
