# Security and Privacy Notes

## Implemented controls reviewed in Phase 7.4

- Argon2 password hashing and generic invalid-credential responses.
- Signed, expiring JWTs stored in an HttpOnly browser cookie.
- Double-submit CSRF protection for cookie-authenticated mutations.
- Explicit user ownership checks in document, vector, and chat operations.
- Private server-side PDF paths; no public static upload route.
- PDF extension, MIME, size, header, structure, encryption, and corruption checks.
- React text rendering for model output and excerpts; no `dangerouslySetInnerHTML` use.
- Safe generic top-level server errors and no tokens, passwords, document text, or private paths found in application logging statements.
- Production startup rejects insecure cookies, weak/placeholder JWT secrets, wildcard CORS, empty CORS, and non-HTTPS origins.
- CORS allows only the API's required methods and headers.

The browser does not persist the access token in local or session storage. The login API still returns a bearer token for non-browser API clients; browser code uses only the cookie-backed session and does not store that response token.

## Uploaded content and model safety

PDF text is untrusted evidence. It cannot override system instructions, select another user's documents, or create citations. Citations are constructed from retrieved chunk metadata. Evidence and claim checks reduce unsupported answers but do not eliminate hallucinations.

## Privacy operations required by the deployer

- Establish a lawful basis and user notice for processing financial documents.
- Define retention, access review, backups, deletion, and incident-response policies.
- Avoid logging full questions or document passages unless a reviewed diagnostic mode explicitly requires them.
- Review the privacy terms and data residency of any external LLM provider before enabling it.
- Use a dedicated service account and least-privilege storage/database credentials.
- Protect backups and vector data to the same standard as source PDFs.

## Review scope

This was a targeted source review of application authentication, CSRF, CORS, rendering, ownership boundaries, upload links, errors, and logging. It was not a penetration test, dependency vulnerability audit, cloud configuration audit, cryptographic audit, or complete security assessment. Live PostgreSQL, ChromaDB, reverse proxy, TLS, browser E2E, and LLM integrations were unavailable in this phase.
