"""Offline real-PDF/BGE/BM25 evaluation. Never writes Postgres, Chroma or chats.

The pre-fix route is replayed from the saved baseline. Retrieval uses the real
production BM25 ranking and BGE query model, with an in-memory exact cosine
adapter in place of Chroma. This is NOT live end-to-end/API/Ollama verification.
"""

import argparse
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from uuid import UUID, uuid5

from app.evaluation.phase3a_probe import CASH, PRODUCTS
from app.models import DocumentChunk
from app.services import keyword_retrieval
from app.services.claim_verifier import ClaimVerifier
from app.services.embedding_service import EmbeddingService, EmbeddingServiceError
from app.services.evidence_page_selector import EvidencePageSelector
from app.services.evidence_verifier import EvidenceVerifier
from app.services.financial_calculation import calculate, cash_flow_summary
from app.services.pdf_processor import ExtractedPage
from app.services.question_requirements import QuestionRequirementAnalyzer
from app.services.rank_fusion import reciprocal_rank_fusion
from app.services.text_chunker import chunk_pages


def run(root, repetitions=10):
    fixtures = sorted((root / "tests/fixtures").glob("*Report.json"))
    user = UUID(int=500)
    all_rows, pages_by_document, metadata = [], {}, []
    for path in fixtures:
        data = json.loads(path.read_text(encoding="utf-8"))
        document = uuid5(user, data["filename"])
        pages = [
            ExtractedPage(document, data["filename"], p["page_number"], p["text"])
            for p in data["pages"]
        ]
        chunks = chunk_pages(pages, document_id=document, user_id=user)
        pages_by_document[document] = pages
        all_rows.extend(
            (
                DocumentChunk(
                    id=c.id,
                    user_id=user,
                    document_id=document,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    page_numbers=c.page_numbers,
                    token_count=c.token_count,
                ),
                data["filename"],
            )
            for c in chunks
        )
        metadata.append(
            {
                "filename": data["filename"],
                "sha256": data["sha256"],
                "pages": len(pages),
                "chunks": len(chunks),
            }
        )
    service = keyword_retrieval.KeywordRetrievalService()
    index = service._build_index(all_rows, service.k1, service.b, service.epsilon)
    service._cache[user] = index

    async def inline(function, *args):
        return function(*args)

    def keyword(query, documents):
        # Cache-only coroutine has no remaining IO/await suspension. Run the
        # production ranker synchronously in this isolated offline adapter.
        coroutine = service.search_keyword(query, user, documents, 5, db=None)
        original_threadpool = keyword_retrieval.run_in_threadpool
        keyword_retrieval.run_in_threadpool = inline
        try:
            coroutine.send(None)
        except StopIteration as result:
            return result.value
        finally:
            coroutine.close()
            keyword_retrieval.run_in_threadpool = original_threadpool
        raise RuntimeError("Unexpected IO in cache-only evaluation")

    result = {
        "scope": __doc__,
        "pdf_fixtures": metadata,
        "repetitions": repetitions,
        "top_k": 5,
        "live_services_used": False,
    }
    # All extraction/verification can run without loading neural dependencies.
    riverton = [
        item.result for item in index.items if "Riverton" in item.result.filename
    ]
    summary = cash_flow_summary(CASH, riverton)
    result["cash_summary"] = asdict(summary) if summary else None
    result["cash_claims"] = (
        ClaimVerifier().verify(summary.answer, riverton, question=CASH).as_dict()
        if summary
        else None
    )
    result["baseline_margin"] = []
    for item in metadata:
        document = uuid5(user, item["filename"])
        rows = [
            entry.result
            for entry in index.items
            if entry.result.document_id == document
        ]
        year = "2024" if "FY2024" in item["filename"] else "2025"
        proof = calculate(f"Calculate gross profit margin for FY{year}.", rows)
        result["baseline_margin"].append(
            {
                "filename": item["filename"],
                "answer": proof.answer if proof else None,
                "claims": ClaimVerifier()
                .verify(proof.answer, rows)
                .overall_status.value
                if proof
                else None,
            }
        )

    northstar = next(
        doc
        for doc, pages in pages_by_document.items()
        if pages[0].filename.startswith("Northstar_Components_FY2024")
    )
    requirements = QuestionRequirementAnalyzer().analyze(PRODUCTS)
    old_requirements = replace(
        requirements,
        metrics=("sales",),
        metric_aliases={"sales": ("sales", "revenue", "turnover")},
        requires_numeric_values=True,
    )

    before_rows = keyword(PRODUCTS, [northstar])
    # Replay the unchanged page scorer under the recorded pre-fix numeric sales
    # requirements. This isolates the original commentary-loss mechanism.
    scored = [
        (
            EvidencePageSelector._score_page(
                PRODUCTS, p.extracted_text, old_requirements
            ),
            p,
        )
        for p in pages_by_document[northstar]
    ]
    best = max((pair for pair in scored if pair[0][1]), key=lambda pair: pair[0][0])[1]
    result["before_replayed"] = {
        "strategy": "keyword",
        "ranked_chunk_pages": [x.page_numbers for x in before_rows],
        "refined_page": best.page_number,
        "commentary_survives_refinement": "distributor-focused sales model"
        in best.extracted_text,
    }
    try:
        import torch

        torch.set_num_threads(1)
        os.environ["HF_HOME"] = str(root / ".model-cache")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        embeddings = EmbeddingService(
            "BAAI/bge-small-en-v1.5",
            expected_dimension=384,
            query_prefix="Represent this sentence for searching relevant passages: ",
            local_files_only=True,
            device="cpu",
            model_revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        )
        vectors = embeddings.embed_documents(
            [entry.result.chunk_text for entry in index.items]
        )
        embeddings.embed_query(PRODUCTS)  # warm model, excluded from measurements
    except (ImportError, OSError, RuntimeError, EmbeddingServiceError) as error:
        result["retrieval_measurement"] = {
            "status": "not_run",
            "error_type": type(error).__name__,
        }
        return result
    before_times, after_times = [], []
    for _ in range(repetitions):
        start = perf_counter()
        keyword(PRODUCTS, [northstar])
        for p in pages_by_document[northstar]:
            EvidencePageSelector._score_page(
                PRODUCTS, p.extracted_text, old_requirements
            )
        before_times.append((perf_counter() - start) * 1000)
        start = perf_counter()
        lexical = keyword(PRODUCTS, [northstar])
        query = embeddings.embed_query(PRODUCTS)
        semantic = [
            replace(
                entry.result,
                similarity_score=sum(a * b for a, b in zip(query, vector, strict=True)),
            )
            for entry, vector in zip(index.items, vectors, strict=True)
            if entry.result.document_id == northstar
        ]
        semantic = sorted(
            [row for row in semantic if row.similarity_score >= 0.25],
            key=lambda row: row.similarity_score,
            reverse=True,
        )[:5]
        fused = [
            entry.result
            for entry in reciprocal_rank_fusion(
                {"keyword": lexical, "semantic": semantic}, top_k=5
            )
        ]
        after_times.append((perf_counter() - start) * 1000)
    evidence = EvidenceVerifier().verify(
        PRODUCTS, fused, user_id=user, allowed_document_ids={northstar}
    )
    result["retrieval_measurement"] = {
        "status": "offline_real_bge_exact_cosine",
        "torch_threads": 1,
        "model": embeddings.model_name,
        "before_mean_ms": mean(before_times),
        "before_median_ms": median(before_times),
        "after_mean_ms": mean(after_times),
        "after_median_ms": median(after_times),
        "after_chunk_pages": [row.page_numbers for row in fused],
        "commentary_retrieved": any(
            "distributor-focused sales model" in row.chunk_text for row in fused
        ),
        "evidence_status": evidence.evidence_status.value,
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = run(Path(__file__).parents[2])
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(data, output, indent=2, default=str)
