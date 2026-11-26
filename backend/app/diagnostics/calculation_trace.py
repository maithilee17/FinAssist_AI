"""Read-only calculation trace for one explicitly selected user's document.

Run inside the deployed backend. No auth tokens, chat writes, indexing, or model
generation are needed. Passage text is written only to an explicitly named new
output file, never to application logs or a default shared report.
"""

import argparse
import asyncio
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from app.config import get_settings
from app.database import AsyncSessionLocal, close_database
from app.models import Document, DocumentChunk, DocumentPage
from app.services.document_processor import build_processing_artifacts
from app.services.financial_calculation import (
    calculate,
    calculation_kind,
    calculation_period_error,
    extract_calculation_inputs,
)
from app.services.rag_dependencies import get_rag_pipeline, get_vector_store


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def snapshot(item, user_id, document_id):
    # Defense in depth: a buggy retrieval response must not disclose another
    # account's text, filename, or identifiers through the diagnostic.
    if item.user_id != user_id or item.document_id != document_id:
        return {"redacted_out_of_scope": True}
    value = asdict(item)
    value["text_sha256"] = digest(item.chunk_text)
    facts, invalid = extract_calculation_inputs([item])
    value["extracted_inputs"] = {key: asdict(fact) for key, fact in facts.items()}
    value["invalid_input_labels"] = sorted(invalid)
    return value


class TraceRetrieval:
    def __init__(self, base, attempts, user_id, document_id):
        self.base, self.attempts = base, attempts
        self.user_id, self.document_id = user_id, document_id

    async def retrieve(self, *args, **kwargs):
        result = await self.base.retrieve(*args, **kwargs)
        self.attempts.append(
            {
                "top_k": kwargs.get("top_k"),
                "retrieval": result.diagnostics.as_dict(),
                "component_rankings": result.component_rankings,
                "returned_passages": [
                    snapshot(x, self.user_id, self.document_id)
                    for x in result.retrieved_chunks
                ],
            }
        )
        return result


class TraceVerifier:
    def __init__(self, base, attempts, user_id, document_id):
        self.base, self.attempts = base, attempts
        self.user_id, self.document_id = user_id, document_id

    def verify(self, question, evidence, **kwargs):
        result = self.base.verify(question, evidence, **kwargs)
        attempt = self.attempts[-1]
        attempt["verifier_passages"] = [
            snapshot(x, self.user_id, self.document_id) for x in evidence
        ]
        attempt["retrieval_equals_verifier"] = (
            attempt["returned_passages"] == attempt["verifier_passages"]
        )
        valid_ids = set(result.valid_chunk_ids)
        valid = [x for x in evidence if x.chunk_id in valid_ids]
        attempt["parser_called"] = result.source_validity_score == 1.0
        attempt["parser_passages"] = (
            [snapshot(x, self.user_id, self.document_id) for x in valid]
            if attempt["parser_called"]
            else []
        )
        proof = calculate(question, valid) if attempt["parser_called"] else None
        attempt["period_error"] = calculation_period_error(question, valid)
        attempt["calculation"] = asdict(proof) if proof else None
        attempt["verification"] = result.as_dict()
        return result


class NoGeneration:
    model_name = "diagnostic-no-generation"

    async def generate(self, *args, **kwargs):
        raise RuntimeError("Diagnostic refused an unexpected generation request")


async def run(args):
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        # This diagnostic targets the deployed PostgreSQL application only.
        await db.execute(text("SET TRANSACTION READ ONLY"))
        statement = select(Document).where(Document.user_id == args.user_id)
        if args.document_id:
            statement = statement.where(Document.id == args.document_id)
        else:
            filename = args.filename
            names = (
                [filename, filename + ".pdf"]
                if not filename.lower().endswith(".pdf")
                else [filename]
            )
            statement = statement.where(Document.filename.in_(names))
        documents = list((await db.scalars(statement)).all())
        if len(documents) != 1:
            raise ValueError(
                "Expected exactly one owned document; use its exact document UUID"
            )
        document = documents[0]
        document_id = document.id
        chunks = list(
            (
                await db.scalars(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.user_id == args.user_id,
                        DocumentChunk.document_id == document_id,
                    )
                    .order_by(DocumentChunk.chunk_index)
                )
            ).all()
        )
        pages = list(
            (
                await db.scalars(
                    select(DocumentPage)
                    .where(
                        DocumentPage.document_id == document_id,
                    )
                    .order_by(DocumentPage.page_number)
                )
            ).all()
        )

        # Open existing collection only. Production retrieval is then bound to
        # this handle so get_or_create_collection cannot mutate the service.
        import chromadb

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            ssl=settings.chroma_ssl,
        )
        collection = client.get_collection(settings.chroma_collection)
        store = get_vector_store()
        store._collection = collection
        records = collection.get(
            where=store._where(args.user_id, [document_id]),
            include=["documents", "metadatas"],
        )
        vector_records = []
        relational = {str(c.id): c for c in chunks}
        for key, content, metadata in zip(
            records["ids"], records["documents"], records["metadatas"], strict=True
        ):
            if metadata.get("user_id") != str(args.user_id) or metadata.get(
                "document_id"
            ) != str(document_id):
                vector_records.append({"redacted_out_of_scope": True})
                continue
            row = relational.get(key)
            vector_records.append(
                {
                    "chunk_id": key,
                    "metadata": metadata,
                    "chunk_text": content,
                    "text_sha256": digest(content),
                    "matches_postgres_text": row is not None and content == row.text,
                    "matches_postgres_pages": row is not None
                    and json.loads(metadata.get("page_numbers_json", "[]"))
                    == row.page_numbers,
                    "matches_postgres_chunk_id": metadata.get("chunk_id") == key,
                    "matches_postgres_filename": metadata.get("filename")
                    == document.filename,
                }
            )
        source = (settings.upload_dir / document.storage_path).resolve()
        root = settings.upload_dir.resolve()
        if root not in source.parents:
            raise ValueError("Stored source path is outside private upload storage")
        fresh = build_processing_artifacts(
            document,
            source,
            target_size=settings.chunk_size_tokens,
            overlap_size=settings.chunk_overlap_tokens,
        )
        same_pages = [(p.page_number, p.extracted_text) for p in pages] == [
            (p.page_number, p.extracted_text) for p in fresh.extraction.pages
        ]
        same_chunks = [(str(c.id), c.text, c.page_numbers) for c in chunks] == [
            (str(c.id), c.text, c.page_numbers) for c in fresh.chunks
        ]
        attempts = []
        pipeline = get_rag_pipeline()
        pipeline.retrieval_service = TraceRetrieval(
            pipeline.retrieval_service,
            attempts,
            args.user_id,
            document_id,
        )
        pipeline.evidence_verifier = TraceVerifier(
            pipeline.evidence_verifier,
            attempts,
            args.user_id,
            document_id,
        )
        # The pipeline's actual retrieval, page selection, sufficiency loop,
        # arithmetic, source builder, and claim verifier all run unchanged.
        pipeline.llm_service = NoGeneration()
        result = await pipeline.answer(
            db, user_id=args.user_id, question=args.question, document_ids=[document_id]
        )
        return {
            "user_id": args.user_id,
            "document_id": document_id,
            "filename": document.filename,
            "question": args.question,
            "fresh_pdf_pages_match_postgres": same_pages,
            "fresh_pdf_chunks_match_postgres": same_chunks,
            "postgres_chunk_ids": [c.id for c in chunks],
            "chroma_records": vector_records,
            "attempts": attempts,
            "result": asdict(result),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, type=UUID)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--document-id", type=UUID)
    scope.add_argument("--filename")
    parser.add_argument(
        "--question", default="Calculate gross profit margin for FY2025."
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not calculation_kind(args.question) or "calculate" not in args.question.lower():
        parser.error("Only explicit financial calculation questions are supported")
    if args.output.exists():
        parser.error("Output already exists; choose a new private file")
    # Library/client exceptions can contain request details. Do not emit them.
    logging.disable(logging.CRITICAL)

    async def execute():
        try:
            return await run(args)
        finally:
            await close_database()

    try:
        report = asyncio.run(execute())
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - never echo provider/DB errors containing credentials
        parser.exit(
            1,
            "Trace could not complete; no complete report written. Check service access, document scope, and output path.\n",
        )
    print("Scoped read-only trace saved. No documents or chat history were changed.")


if __name__ == "__main__":
    main()
