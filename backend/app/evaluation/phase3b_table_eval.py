"""Read-only PDF/BGE/BM25/RRF evaluation. No live database, Chroma or Ollama writes.

Run from backend: python -m app.evaluation.phase3b_table_eval --pdf-dir PATH --output PATH
Uses cached BGE offline; actual vector indexing and complete model answers are not simulated as live.
"""

import argparse
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import UUID, uuid5

from app.models.document import DocumentChunk
from app.services import keyword_retrieval
from app.services.claim_verifier import ClaimVerifier
from app.services.embedding_service import EmbeddingService
from app.services.evidence_verifier import EvidenceVerifier
from app.services.financial_calculation import calculate, cash_flow_summary
from app.services.financial_table_extractor import decode_table_chunk, render_table
from app.services.pdf_processor import extract_pdf_pages
from app.services.rank_fusion import reciprocal_rank_fusion
from app.services.text_chunker import chunk_pages

NAMES = (
    "FinAssist_Sample_Financial_Report.pdf",
    "Northstar_Components_FY2024_Test_Report.pdf",
    "Riverton_Industries_FY2025_Test_Report.pdf",
)


def run(pdf_dir: Path, root: Path) -> dict:
    user = UUID(int=900)
    documents = []
    rows = []
    legacy_rows = []
    all_results = {}
    baseline = json.loads(
        (root / "reports/phase3b_baseline.json").read_text(encoding="utf-8")
    )
    for path in [
        root / "reports/phase3b_fixtures/three_year.pdf",
        *(pdf_dir / name for name in NAMES),
    ]:
        doc = uuid5(user, path.name)
        extraction, chunking = [], []
        for _ in range(5):
            start = perf_counter()
            result = extract_pdf_pages(path, doc, path.name)
            split = perf_counter()
            chunks = chunk_pages(result.pages, document_id=doc, user_id=user)
            end = perf_counter()
            extraction.append((split - start) * 1000)
            chunking.append((end - split) * 1000)
        old = next(x for x in baseline["documents"] if x["filename"] == path.name)
        hashes = [
            hashlib.sha256(p.extracted_text.encode()).hexdigest() for p in result.pages
        ]
        documents.append(
            {
                "filename": path.name,
                "pages": result.page_count,
                "chunks": len(chunks),
                "baseline_chunks": old["chunks"],
                "page_text_unchanged": hashes == old["page_text_sha256"],
                "tables": sum(
                    len(p.metadata["financial_tables"]) for p in result.pages
                ),
                "mean_extraction_ms": mean(extraction),
                "baseline_extraction_ms": old["mean_extraction_ms"],
                "mean_chunking_ms": mean(chunking),
                "baseline_chunking_ms": old["mean_chunking_ms"],
                "table_timings_ms": [
                    p.metadata["table_timings_ms"] for p in result.pages
                ],
            }
        )
        all_results[path.name] = doc
        legacy_chunks = chunk_pages(
            [replace(p, metadata={}) for p in result.pages],
            document_id=doc,
            user_id=user,
        )
        for c in legacy_chunks:
            legacy_rows.append(
                (
                    DocumentChunk(
                        id=c.id,
                        user_id=user,
                        document_id=doc,
                        chunk_index=c.chunk_index,
                        text=c.text,
                        page_numbers=c.page_numbers,
                        token_count=c.token_count,
                    ),
                    path.name,
                )
            )
        documents[-1]["unchanged_document_chunk_ids_preserved"] = (
            [c.id for c in chunks] == [c.id for c in legacy_chunks]
            if not any(p.metadata["financial_tables"] for p in result.pages)
            else None
        )
        for c in chunks:
            rows.append(
                (
                    DocumentChunk(
                        id=c.id,
                        user_id=user,
                        document_id=doc,
                        chunk_index=c.chunk_index,
                        text=c.text,
                        page_numbers=c.page_numbers,
                        token_count=c.token_count,
                    ),
                    path.name,
                )
            )
    ranker = keyword_retrieval.KeywordRetrievalService()
    index = ranker._build_index(rows, ranker.k1, ranker.b, ranker.epsilon)
    ranker._cache[user] = index
    legacy_ranker = keyword_retrieval.KeywordRetrievalService()
    legacy_index = legacy_ranker._build_index(
        legacy_rows, legacy_ranker.k1, legacy_ranker.b, legacy_ranker.epsilon
    )
    legacy_ranker._cache[user] = legacy_index

    async def inline(function, *args):
        return function(*args)

    def keyword(question, doc, active_ranker=ranker):
        coroutine = active_ranker.search_keyword(question, user, [doc], 5, db=None)
        previous = keyword_retrieval.run_in_threadpool
        keyword_retrieval.run_in_threadpool = inline
        try:
            coroutine.send(None)
        except StopIteration as completed:
            return completed.value
        finally:
            coroutine.close()
            keyword_retrieval.run_in_threadpool = previous
        raise RuntimeError("Unexpected I/O in offline ranker")

    os.environ["HF_HOME"] = str(root / "backend/.model-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch

    torch.set_num_threads(1)
    embeddings = EmbeddingService(
        "BAAI/bge-small-en-v1.5",
        expected_dimension=384,
        query_prefix="Represent this sentence for searching relevant passages: ",
        local_files_only=True,
        device="cpu",
        model_revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    )
    start = perf_counter()
    vectors = embeddings.embed_documents([x.result.chunk_text for x in index.items])
    embed_ms = (perf_counter() - start) * 1000
    start = perf_counter()
    legacy_vectors = embeddings.embed_documents(
        [x.result.chunk_text for x in legacy_index.items]
    )
    legacy_embed_warm_ms = (perf_counter() - start) * 1000
    start = perf_counter()
    vectors = embeddings.embed_documents([x.result.chunk_text for x in index.items])
    table_embed_warm_ms = (perf_counter() - start) * 1000
    embeddings.embed_query("Calculate gross profit margin in FY2025")
    model = embeddings._load_model()
    rendered = [
        render_table(t)
        for x in index.items
        if (t := decode_table_chunk(x.result.chunk_text))
    ]
    token_lengths = [len(model.tokenizer.encode(t)) for t in rendered]
    cases = [
        ("three_year.pdf", "Calculate gross profit margin in FY2025", "35.00%"),
        ("three_year.pdf", "Calculate revenue growth from FY2024 to FY2025", "26.32%"),
        (NAMES[0], "Calculate gross profit margin in FY2025", "40.00%"),
        (NAMES[1], "Calculate gross profit margin in FY2024", "37.50%"),
        (NAMES[2], "Calculate gross profit margin in FY2025", "35.00%"),
        (
            NAMES[1],
            "What products did Northstar Components manufacture in FY2024 and what was its sales model?",
            "distributor-focused sales model",
        ),
        (
            NAMES[2],
            "Summarize the cash flows for Riverton Industries in FY2025 including operating, investing, and financing activities and net change in cash.",
            "Verified cash flow summary",
        ),
        (NAMES[2], "What was inventory in FY2025?", None),
        ("three_year.pdf", "Calculate gross profit margin in FY2022", None),
    ]
    measured = []
    for filename, question, expected in cases:
        doc = all_results[filename]
        latencies = []
        legacy_latencies = []
        for _ in range(5):
            start = perf_counter()
            old_lexical = keyword(question, doc, legacy_ranker)
            old_query = embeddings.embed_query(question)
            old_semantic = sorted(
                [
                    replace(
                        item.result,
                        similarity_score=sum(
                            a * b for a, b in zip(old_query, v, strict=True)
                        ),
                    )
                    for item, v in zip(legacy_index.items, legacy_vectors, strict=True)
                    if item.result.document_id == doc
                ],
                key=lambda x: x.similarity_score,
                reverse=True,
            )[:5]
            old_fused = [
                x.result
                for x in reciprocal_rank_fusion(
                    {"keyword": old_lexical, "semantic": old_semantic}, top_k=5
                )
            ]
            legacy_latencies.append((perf_counter() - start) * 1000)
            start = perf_counter()
            lexical = keyword(question, doc)
            query = embeddings.embed_query(question)
            semantic = sorted(
                [
                    replace(
                        item.result,
                        similarity_score=sum(
                            a * b for a, b in zip(query, v, strict=True)
                        ),
                    )
                    for item, v in zip(index.items, vectors, strict=True)
                    if item.result.document_id == doc
                ],
                key=lambda x: x.similarity_score,
                reverse=True,
            )[:5]
            fused = [
                x.result
                for x in reciprocal_rank_fusion(
                    {"keyword": lexical, "semantic": semantic}, top_k=5
                )
            ]
            latencies.append((perf_counter() - start) * 1000)
        # Replay the bounded same-table row expansion using this in-memory corpus.
        seeds = {t.table_id for x in fused if (t := decode_table_chunk(x.chunk_text))}
        expanded = {x.chunk_id: x for x in fused}
        for entry in index.items:
            item = entry.result
            table = decode_table_chunk(item.chunk_text)
            if item.document_id == doc and table and table.table_id in seeds:
                expanded.setdefault(item.chunk_id, item)
        evidence = list(expanded.values())
        start = perf_counter()
        proof = cash_flow_summary(question, evidence) or calculate(question, evidence)
        calc_ms = (perf_counter() - start) * 1000
        decision = EvidenceVerifier().verify(
            question, evidence, user_id=user, allowed_document_ids={doc}
        )
        claims = (
            ClaimVerifier().verify(proof.answer, evidence, question=question)
            if proof
            else None
        )
        corpus = "\n".join(x.chunk_text for x in evidence)
        passed = (
            bool(proof and expected in proof.answer)
            if expected and "products" not in question
            else expected in corpus and decision.evidence_status.value == "sufficient"
            if expected
            else proof is None and decision.evidence_status.value != "sufficient"
        )
        legacy_proof = cash_flow_summary(question, old_fused) or calculate(
            question, old_fused
        )
        measured.append(
            {
                "filename": filename,
                "question": question,
                "expected": expected,
                "pass": passed,
                "answer": proof.answer if proof else None,
                "evidence_status": decision.evidence_status.value,
                "claim_status": claims.overall_status.value if claims else None,
                "mean_retrieval_ms": mean(latencies),
                "legacy_text_replay_mean_retrieval_ms": mean(legacy_latencies),
                "legacy_calculation_answer": legacy_proof.answer
                if legacy_proof
                else None,
                "calculation_ms": calc_ms,
                "chunks": [
                    {
                        "chunk_id": str(x.chunk_id),
                        "document_id": str(x.document_id),
                        "pages": x.page_numbers,
                    }
                    for x in evidence
                ],
            }
        )
    comparison_rows = [
        entry.result
        for entry in index.items
        if entry.result.document_id in {all_results[NAMES[0]], all_results[NAMES[2]]}
    ]
    northstar_source = next(
        i
        for i, x in enumerate(comparison_rows, 1)
        if (t := decode_table_chunk(x.chunk_text))
        and any(r.label == "Revenue" for r in t.rows)
    )
    riverton_source = next(
        i
        for i, x in enumerate(comparison_rows, 1)
        if x.document_id == all_results[NAMES[2]] and "$1,200,000" in x.chunk_text
    )
    comparison_question = "Compare revenue and net income for Northstar Components and Riverton Industries in FY2025."
    # Handwritten source-grounded expected claims. This verifies claim checking;
    # it is not represented as an Ollama-generated answer or a live RAG test.
    comparison_answer = f"Northstar Components FY2025 revenue was USD 850,000 and net income was USD 96,000 [Source {northstar_source}].\nRiverton Industries FY2025 revenue was USD 1,200,000 and net income was USD 91,000 [Source {riverton_source}]."
    comparison_evidence = EvidenceVerifier().verify(
        comparison_question,
        comparison_rows,
        user_id=user,
        allowed_document_ids={all_results[NAMES[0]], all_results[NAMES[2]]},
    )
    comparison_claims = ClaimVerifier().verify(
        comparison_answer, comparison_rows, question=comparison_question
    )
    return {
        "scope": __doc__,
        "live_services_used": False,
        "documents": documents,
        "model": "BAAI/bge-small-en-v1.5",
        "embedding_cold_including_model_load_ms": embed_ms,
        "embedding_legacy_corpus_warm_ms": legacy_embed_warm_ms,
        "embedding_table_corpus_warm_ms": table_embed_warm_ms,
        "max_rendered_table_bge_tokens": max(token_lengths, default=0),
        "cases": measured,
        "cross_document_factual_claim_check": {
            "scope": "complete selected offline corpus; hand-authored expected claims, not LLM output",
            "question": comparison_question,
            "expected_claims": comparison_answer,
            "evidence_status": comparison_evidence.evidence_status.value,
            "claim_status": comparison_claims.overall_status.value,
            "calculator_did_not_omit_legacy_issuer": calculate(
                comparison_question, comparison_rows
            )
            is None,
        },
        "not_measured": [
            "Chroma indexing",
            "PostgreSQL persistence",
            "complete Ollama answers",
            "GUI",
            "restart persistence",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.pdf_dir, Path(__file__).resolve().parents[3])
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": len(result["cases"]),
                "passed": sum(x["pass"] for x in result["cases"]),
                "max_table_bge_tokens": result["max_rendered_table_bge_tokens"],
            }
        )
    )
