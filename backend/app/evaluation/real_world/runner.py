"""Run FinAssist's production extraction/retrieval/verifier stack on public filings.

The default run intentionally does not call an LLM. It exercises the real PyMuPDF
extractor, chunker, BGE model, BM25 index, adaptive router, RRF, evidence verifier,
claim verifier, citation checks, and confidence scorer. Chroma is replaced only by
an evaluation-local exact cosine store because the normal Chroma service is an
external runtime dependency; the same production SemanticRetrievalService is used.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base
from app.models import Document, DocumentChunk, DocumentStatus, User
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalSelector,
    AdaptiveRetrievalService,
)
from app.services.claim_verifier import ClaimVerifier
from app.services.confidence_service import ConfidenceService
from app.services.embedding_service import EmbeddingService
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.keyword_retrieval import KeywordRetrievalService
from app.services.pdf_processor import extract_pdf_pages, inspect_pdf
from app.services.query_analyzer import FinancialQueryAnalyzer
from app.services.retrieval_service import SemanticRetrievalService
from app.services.text_chunker import TextChunk, chunk_pages
from app.services.vector_store import VectorSearchResult

ROOT = Path(__file__).resolve().parent
DOCUMENTS_DIR = ROOT / "documents"
MANIFEST_PATH = ROOT / "source_manifest.json"
DATASET_PATH = ROOT / "dataset.json"
RESULTS_PATH = ROOT / "results.json"
REPORT_PATH = ROOT / "report.md"
CACHE_DIR = ROOT / ".cache"
REPRODUCIBILITY_PATH = ROOT / "reproducibility.json"
USER_ID = UUID("61000000-0000-0000-0000-000000000001")


@dataclass(slots=True)
class IndexedChunk:
    chunk: TextChunk
    filename: str
    embedding: list[float]


class ExactCosineVectorStore:
    """Evaluation-only exact vector store with production-compatible search output."""

    def __init__(self) -> None:
        self.items: list[IndexedChunk] = []

    def add(
        self, chunks: list[TextChunk], filename: str, embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts differ")
        self.items.extend(
            IndexedChunk(chunk, filename, embedding)
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        )

    def search_similar_chunks(
        self,
        query_embedding: list[float],
        *,
        user_id: UUID,
        document_ids: list[UUID] | None = None,
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        selected = set(document_ids or [])
        scored: list[tuple[float, IndexedChunk]] = []
        for item in self.items:
            if item.chunk.user_id != user_id:
                continue
            if selected and item.chunk.document_id not in selected:
                continue
            score = sum(
                a * b for a, b in zip(query_embedding, item.embedding, strict=True)
            )
            scored.append((float(score), item))
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].chunk.id)))
        return [
            VectorSearchResult(
                chunk_id=item.chunk.id,
                user_id=item.chunk.user_id,
                document_id=item.chunk.document_id,
                filename=item.filename,
                page_numbers=item.chunk.page_numbers,
                chunk_text=item.chunk.text,
                similarity_score=score,
            )
            for score, item in scored[:top_k]
        ]


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _classification(predicted: list[bool], actual: list[bool]) -> dict[str, float]:
    tp = sum(p and a for p, a in zip(predicted, actual, strict=True))
    fp = sum(p and not a for p, a in zip(predicted, actual, strict=True))
    fn = sum(not p and a for p, a in zip(predicted, actual, strict=True))
    return {
        "precision": round(_safe_div(tp, tp + fp), 6),
        "recall": round(_safe_div(tp, tp + fn), 6),
    }


def _validate_sources(manifest: dict[str, object]) -> list[dict[str, object]]:
    validated = []
    for document in manifest["documents"]:
        path = DOCUMENTS_DIR / document["local_filename"]
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing {path.name}; download it from {document['source_url']}"
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        page_count = inspect_pdf(path)
        if digest != document["sha256"]:
            raise ValueError(f"SHA-256 mismatch for {path.name}")
        if path.stat().st_size != document["file_size_bytes"]:
            raise ValueError(f"File-size mismatch for {path.name}")
        if page_count != document["pdf_page_count"]:
            raise ValueError(f"Page-count mismatch for {path.name}")
        validated.append({**document, "validated": True})
    return validated


def _page_match(
    case: dict[str, object], retrieved: list[VectorSearchResult]
) -> bool | None:
    expected_pages = {int(value) for value in case["expected_pages"]}
    if not expected_pages:
        return None
    allowed_documents = {UUID(value) for value in case["document_ids"]}
    found = {
        page
        for item in retrieved
        if item.document_id in allowed_documents
        for page in item.page_numbers
        if page in expected_pages
    }
    if case.get("page_match_mode", "any") == "all":
        return found == expected_pages
    return bool(found)


def _source_numbers(
    case: dict[str, object], retrieved: list[VectorSearchResult]
) -> list[int]:
    expected_pages = {int(value) for value in case["expected_pages"]}
    allowed_documents = {UUID(value) for value in case["document_ids"]}
    return [
        index
        for index, item in enumerate(retrieved, start=1)
        if item.document_id in allowed_documents
        and expected_pages.intersection(item.page_numbers)
    ]


def _excerpt(text: str, limit: int = 700) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _service_fingerprint() -> str:
    service_dir = Path(__file__).resolve().parents[2] / "services"
    digest = hashlib.sha256()
    for filename in ("pdf_processor.py", "text_cleaner.py", "text_chunker.py"):
        digest.update((service_dir / filename).read_bytes())
    return digest.hexdigest()


def _chunk_fingerprint(chunks: list[TextChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(str(chunk.id).encode())
        digest.update(chunk.text.encode("utf-8"))
    return digest.hexdigest()


def _load_or_create_chunks(
    source: dict[str, object], settings: object
) -> tuple[list[TextChunk], dict[str, object], bool]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    document_id = UUID(str(source["document_id"]))
    cache_stem = CACHE_DIR / str(document_id)
    metadata_path = cache_stem.with_suffix(".chunks.meta.json")
    chunks_path = cache_stem.with_suffix(".chunks.json")
    expected = {
        "source_sha256": source["sha256"],
        "service_fingerprint": _service_fingerprint(),
        "chunk_size_tokens": settings.chunk_size_tokens,
        "chunk_overlap_tokens": settings.chunk_overlap_tokens,
    }
    if metadata_path.is_file() and chunks_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if all(metadata.get(key) == value for key, value in expected.items()):
            serialized = json.loads(chunks_path.read_text(encoding="utf-8"))
            chunks = [
                TextChunk(
                    id=UUID(value["id"]),
                    document_id=UUID(value["document_id"]),
                    user_id=UUID(value["user_id"]),
                    chunk_index=int(value["chunk_index"]),
                    text=value["text"],
                    token_count=int(value["token_count"]),
                    page_numbers=[int(page) for page in value["page_numbers"]],
                )
                for value in serialized
            ]
            if metadata.get("chunk_count") == len(chunks):
                return chunks, metadata, True

    path = DOCUMENTS_DIR / str(source["local_filename"])
    extraction_started = perf_counter()
    extraction = extract_pdf_pages(path, document_id, str(source["local_filename"]))
    extraction_ms = (perf_counter() - extraction_started) * 1000
    chunks = chunk_pages(
        extraction.pages,
        document_id=document_id,
        user_id=USER_ID,
        target_size=settings.chunk_size_tokens,
        overlap_size=settings.chunk_overlap_tokens,
    )
    serialized = [
        {
            "id": str(chunk.id),
            "document_id": str(chunk.document_id),
            "user_id": str(chunk.user_id),
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "token_count": chunk.token_count,
            "page_numbers": chunk.page_numbers,
        }
        for chunk in chunks
    ]
    metadata = {
        **expected,
        "document_id": str(document_id),
        "filename": source["local_filename"],
        "page_count": extraction.page_count,
        "empty_pages": sum(not page.extracted_text for page in extraction.pages),
        "extracted_characters": sum(
            len(page.extracted_text) for page in extraction.pages
        ),
        "chunk_count": len(chunks),
        "chunk_fingerprint": _chunk_fingerprint(chunks),
        "extraction_time_ms": round(extraction_ms, 3),
        "created_at": datetime.now(UTC).isoformat(),
    }
    chunks_path.write_text(json.dumps(serialized) + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return chunks, metadata, False


def _save_embedding_checkpoint(
    path: Path, chunk_ids: list[str], embeddings: list[list[float]]
) -> None:
    temporary = path.with_suffix(".tmp.npz")
    matrix = np.asarray(embeddings, dtype=np.float32)
    np.savez_compressed(temporary, chunk_ids=np.asarray(chunk_ids), embeddings=matrix)
    temporary.replace(path)


def _load_or_create_embeddings(
    source: dict[str, object],
    chunks: list[TextChunk],
    embedding: EmbeddingService,
    *,
    batch_size: int,
) -> tuple[list[list[float]], dict[str, object]]:
    document_id = str(source["document_id"])
    embeddings_path = CACHE_DIR / f"{document_id}.embeddings.npz"
    metadata_path = CACHE_DIR / f"{document_id}.embeddings.meta.json"
    expected_ids = [str(chunk.id) for chunk in chunks]
    chunk_fingerprint = _chunk_fingerprint(chunks)
    expected_metadata = {
        "source_sha256": source["sha256"],
        "chunk_fingerprint": chunk_fingerprint,
        "embedding_model": embedding.model_name,
        "normalized": True,
    }
    vectors: list[list[float]] = []
    loaded_count = 0
    if embeddings_path.is_file() and metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if all(metadata.get(key) == value for key, value in expected_metadata.items()):
            with np.load(embeddings_path, allow_pickle=False) as cache:
                cached_ids = [str(value) for value in cache["chunk_ids"].tolist()]
                cached_matrix = cache["embeddings"]
            if cached_ids == expected_ids[: len(cached_ids)]:
                vectors = cached_matrix.astype(float).tolist()
                loaded_count = len(vectors)

    generated_started = perf_counter()
    for start in range(loaded_count, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        print(
            f"  BGE checkpoint {start + 1}-{start + len(batch)} of {len(chunks)}",
            flush=True,
        )
        vectors.extend(embedding.embed_documents([chunk.text for chunk in batch]))
        completed_ids = expected_ids[: len(vectors)]
        _save_embedding_checkpoint(embeddings_path, completed_ids, vectors)
        checkpoint_metadata = {
            **expected_metadata,
            "document_id": document_id,
            "completed_chunk_count": len(vectors),
            "total_chunk_count": len(chunks),
            "embedding_dimension": len(vectors[0]) if vectors else None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        metadata_path.write_text(
            json.dumps(checkpoint_metadata, indent=2) + "\n", encoding="utf-8"
        )

    elapsed_ms = (perf_counter() - generated_started) * 1000
    return vectors, {
        **expected_metadata,
        "cache_path": str(embeddings_path.relative_to(ROOT)),
        "cache_hit": loaded_count == len(chunks),
        "resumed_embedding_count": loaded_count,
        "generated_embedding_count": len(chunks) - loaded_count,
        "embedding_dimension": len(vectors[0]) if vectors else None,
        "embedding_generation_time_ms": round(elapsed_ms, 3),
    }


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _reproducibility(corpus: dict[str, object]) -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: _version(name)
            for name in (
                "PyMuPDF",
                "sentence-transformers",
                "torch",
                "numpy",
                "rank-bm25",
                "SQLAlchemy",
            )
        },
        "artifacts": {
            "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
            "source_manifest_sha256": hashlib.sha256(
                MANIFEST_PATH.read_bytes()
            ).hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "corpus": corpus,
        "semantic_retrieval_backend": "exact in-memory cosine over normalized production BGE embeddings",
        "chroma_service_exercised": False,
        "llm_generation_enabled": False,
    }


async def _build_runtime(
    documents: list[dict[str, object]],
) -> tuple[
    AsyncSession,
    AdaptiveRetrievalService,
    EvidenceVerifier,
    ClaimVerifier,
    ConfidenceService,
    dict[str, object],
]:
    print("Loading evaluation settings...", flush=True)
    settings = get_settings()
    print("Configuring offline model cache...", flush=True)
    model_cache = Path(__file__).resolve().parents[3] / ".model-cache"
    os.environ.setdefault("HF_HOME", str(model_cache))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    print("Creating isolated evaluation database...", flush=True)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    print("Evaluation database ready.", flush=True)
    session = session_factory()
    session.add(
        User(
            id=USER_ID,
            full_name="Real-world evaluation user",
            email="real-world-evaluation@example.invalid",
            hashed_password="not-a-login-account",
            is_active=True,
        )
    )

    embedding = EmbeddingService(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
        query_prefix=settings.embedding_query_prefix,
    )
    vector_store = ExactCosineVectorStore()
    corpus_stats: dict[str, object] = {
        "embedding_model": settings.embedding_model,
        "vector_backend": "evaluation exact cosine (Chroma service unavailable)",
        "cache_directory": str(CACHE_DIR.relative_to(ROOT)),
        "documents": [],
    }
    for source in documents:
        document_id = UUID(source["document_id"])
        path = DOCUMENTS_DIR / source["local_filename"]
        print(f"Loading or extracting {path.name}...", flush=True)
        chunks, chunk_metadata, chunk_cache_hit = _load_or_create_chunks(
            source, settings
        )
        print(
            f"Loading or embedding {len(chunks)} chunks from {path.name}...",
            flush=True,
        )
        vectors, embedding_metadata = _load_or_create_embeddings(
            source,
            chunks,
            embedding,
            batch_size=settings.embedding_batch_size,
        )
        vector_store.add(chunks, source["local_filename"], vectors)
        print(f"Indexed {path.name} in the evaluation vector store.", flush=True)
        session.add(
            Document(
                id=document_id,
                user_id=USER_ID,
                filename=source["local_filename"],
                storage_path=str(path),
                file_size=path.stat().st_size,
                mime_type="application/pdf",
                page_count=int(chunk_metadata["page_count"]),
                processing_status=DocumentStatus.COMPLETED,
                indexed_chunk_count=len(chunks),
                embedding_model=settings.embedding_model,
                indexed_at=datetime.now(UTC),
            )
        )
        session.add_all(
            DocumentChunk(
                id=chunk.id,
                document_id=chunk.document_id,
                user_id=chunk.user_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                page_numbers=chunk.page_numbers,
            )
            for chunk in chunks
        )
        corpus_stats["documents"].append(
            {
                "document_id": str(document_id),
                "filename": source["local_filename"],
                "pages": chunk_metadata["page_count"],
                "empty_pages": chunk_metadata["empty_pages"],
                "extracted_characters": chunk_metadata["extracted_characters"],
                "chunks": len(chunks),
                "chunk_cache_hit": chunk_cache_hit,
                "chunk_cache_fingerprint": chunk_metadata["chunk_fingerprint"],
                "extraction_time_ms": 0.0
                if chunk_cache_hit
                else chunk_metadata["extraction_time_ms"],
                "embedding_cache": embedding_metadata,
            }
        )
    await session.commit()

    keyword = KeywordRetrievalService(
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        epsilon=settings.bm25_epsilon,
        max_cached_users=settings.bm25_cache_users,
    )
    semantic = SemanticRetrievalService(
        embedding,
        vector_store,  # type: ignore[arg-type]
        default_top_k=settings.rag_top_k,
        minimum_similarity=settings.rag_min_similarity,
    )
    adaptive = AdaptiveRetrievalService(
        keyword,
        semantic,
        analyzer=FinancialQueryAnalyzer(),
        selector=AdaptiveRetrievalSelector(
            exact_term_threshold=settings.adaptive_exact_term_threshold
        ),
        default_top_k=settings.rag_top_k,
        rrf_constant=settings.rrf_constant,
    )
    evidence = EvidenceVerifier(
        relevance_threshold=settings.evidence_relevance_threshold,
        sufficiency_threshold=settings.evidence_sufficiency_threshold,
        weak_threshold=settings.evidence_weak_threshold,
    )
    return (
        session,
        adaptive,
        evidence,
        ClaimVerifier(),
        ConfidenceService(),
        corpus_stats,
    )


async def run() -> dict[str, object]:
    print("Validating report checksums and PDF structure...", flush=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    sources = _validate_sources(manifest)
    print("Report validation complete.", flush=True)
    (
        session,
        adaptive,
        evidence_verifier,
        claim_verifier,
        confidence_service,
        corpus,
    ) = await _build_runtime(sources)
    settings = get_settings()
    records: list[dict[str, object]] = []
    try:
        for case in dataset["cases"]:
            print(f"Evaluating {case['id']}...", flush=True)
            case_started = perf_counter()
            document_ids = [UUID(value) for value in case["document_ids"]]
            allowed_documents = set(document_ids)
            retrieval_attempts = 0
            total_retrieval_ms = 0.0
            verification_ms = 0.0
            retrieved: list[VectorSearchResult] = []
            diagnostics = None
            assessment = None
            top_k = settings.rag_top_k

            while True:
                result = await adaptive.retrieve(
                    session,
                    case["question"],
                    user_id=USER_ID,
                    document_ids=document_ids,
                    top_k=top_k,
                )
                retrieval_attempts += 1
                total_retrieval_ms += result.diagnostics.retrieval_time_ms
                diagnostics = result.diagnostics
                retrieved = list(
                    {
                        item.chunk_id: item
                        for item in [*retrieved, *result.retrieved_chunks]
                    }.values()
                )
                verify_started = perf_counter()
                assessment = evidence_verifier.verify(
                    case["question"],
                    retrieved,
                    user_id=USER_ID,
                    allowed_document_ids=allowed_documents,
                )
                verification_ms += (perf_counter() - verify_started) * 1000
                if assessment.evidence_status != EvidenceStatus.WEAK:
                    break
                if retrieval_attempts > settings.evidence_max_retrieval_attempts:
                    break
                if top_k >= settings.evidence_max_top_k:
                    break
                top_k = min(settings.evidence_max_top_k, top_k + settings.rag_top_k)

            assert diagnostics is not None and assessment is not None
            page_match = _page_match(case, retrieved)
            source_numbers = _source_numbers(case, retrieved)
            claim_result = None
            if case["expected_answer"] and source_numbers:
                citations = " ".join(f"[Source {value}]" for value in source_numbers)
                claim_started = perf_counter()
                claim_result = claim_verifier.verify(
                    f"{case['expected_answer']} {citations}", retrieved
                )
                verification_ms += (perf_counter() - claim_started) * 1000
            confidence = confidence_service.assess(assessment, claim_result)
            answer_permitted = assessment.evidence_status == EvidenceStatus.SUFFICIENT
            observed_output = (
                "Answer generation permitted; LLM generation was disabled for this evaluation run."
                if answer_permitted
                else "I could not find sufficient evidence in the uploaded documents to answer this question."
            )
            records.append(
                {
                    "case_id": case["id"],
                    "company": case["company"],
                    "category": case["category"],
                    "question": case["question"],
                    "expected": {
                        "answerable": case["expected_answerable"],
                        "answer": case["expected_answer"],
                        "pages": case["expected_pages"],
                        "strategy": case["expected_retrieval_strategy"],
                        "verification_outcome": case["expected_verification_outcome"],
                    },
                    "selected_retrieval_strategy": diagnostics.selected_strategy.value,
                    "selection_reason": diagnostics.selection_reason,
                    "retrieval_latency_ms": round(total_retrieval_ms, 3),
                    "retrieval_attempts": retrieval_attempts,
                    "retrieved_passages": [
                        {
                            "rank": rank,
                            "chunk_id": str(item.chunk_id),
                            "document_id": str(item.document_id),
                            "filename": item.filename,
                            "page_numbers": item.page_numbers,
                            "score": round(item.similarity_score, 6),
                            "excerpt": _excerpt(item.chunk_text),
                        }
                        for rank, item in enumerate(retrieved, start=1)
                    ],
                    "evidence": {
                        "status": assessment.evidence_status.value,
                        "relevance_score": assessment.relevance_score,
                        "sufficiency_score": assessment.sufficiency_score,
                        "supported_aspects": assessment.supported_aspects,
                        "missing_aspects": assessment.missing_aspects,
                        "reason": assessment.reason,
                    },
                    "claims": claim_result.as_dict() if claim_result else None,
                    "claims_checked": claim_result.claims_checked
                    if claim_result
                    else 0,
                    "supported_claims": claim_result.supported_claims
                    if claim_result
                    else 0,
                    "unsupported_claims": claim_result.unsupported_claims
                    if claim_result
                    else 0,
                    "citation_page_match": page_match,
                    "matched_source_numbers": source_numbers,
                    "confidence": confidence.as_dict(),
                    "final_decision": "answer_permitted"
                    if answer_permitted
                    else "abstained",
                    "observed_output": observed_output,
                    "verification_latency_ms": round(verification_ms, 3),
                    "end_to_end_latency_ms": round(
                        (perf_counter() - case_started) * 1000, 3
                    ),
                }
            )
    finally:
        await session.close()

    answerability_predictions = [
        record["final_decision"] == "answer_permitted" for record in records
    ]
    answerability_actual = [
        bool(case["expected_answerable"]) for case in dataset["cases"]
    ]
    abstention_predictions = [not value for value in answerability_predictions]
    abstention_actual = [not value for value in answerability_actual]
    answerability = _classification(answerability_predictions, answerability_actual)
    abstention = _classification(abstention_predictions, abstention_actual)
    answerable_records = [
        record
        for record, case in zip(records, dataset["cases"], strict=True)
        if case["expected_answerable"]
    ]
    page_checks = [
        bool(record["citation_page_match"])
        for record in answerable_records
        if record["citation_page_match"] is not None
    ]
    metrics = {
        "case_count": len(records),
        "company_count": len({case["company"] for case in dataset["cases"]}),
        "category_count": len({case["category"] for case in dataset["cases"]}),
        "strategy_selection_accuracy": round(
            mean(
                record["selected_retrieval_strategy"] == record["expected"]["strategy"]
                for record in records
            ),
            6,
        ),
        "evidence_outcome_exact_accuracy": round(
            mean(
                record["evidence"]["status"]
                == record["expected"]["verification_outcome"]
                for record in records
            ),
            6,
        ),
        "answerability_precision": answerability["precision"],
        "answerability_recall": answerability["recall"],
        "abstention_precision": abstention["precision"],
        "abstention_recall": abstention["recall"],
        "citation_page_correctness_on_answerable_cases": round(mean(page_checks), 6),
        "reference_claim_fully_supported_rate": round(
            mean(
                bool(record["claims"])
                and record["claims"]["overall_status"] == "verified"
                for record in answerable_records
            ),
            6,
        ),
        "additional_retrieval_frequency": round(
            mean(record["retrieval_attempts"] > 1 for record in records), 6
        ),
        "average_retrieval_latency_ms": round(
            mean(record["retrieval_latency_ms"] for record in records), 3
        ),
        "average_verification_latency_ms": round(
            mean(record["verification_latency_ms"] for record in records), 3
        ),
        "average_end_to_end_latency_ms_without_llm": round(
            mean(record["end_to_end_latency_ms"] for record in records), 3
        ),
        "generated_answer_correctness": None,
        "llm_cost_per_query_usd": None,
    }
    results = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": dataset["name"],
        "execution": {
            "real_pdfs_processed": True,
            "production_pdf_extractor": True,
            "production_chunker": True,
            "production_bge_model": True,
            "production_bm25": True,
            "production_adaptive_routing_and_rrf": True,
            "production_evidence_claim_confidence_services": True,
            "chroma_service_exercised": False,
            "llm_generation_enabled": False,
            "notes": [
                "Docker/ChromaDB was unavailable, so semantic vectors used an exact in-memory cosine adapter behind the production semantic retrieval service.",
                "No OpenAI, Ollama, or other LLM call was made. Expected answers were used only as manually labelled reference claims for claim/citation verification.",
                "Latency excludes networked Chroma and LLM generation and is not a production end-to-end benchmark.",
            ],
        },
        "sources": sources,
        "corpus": corpus,
        "metrics": metrics,
        "records": records,
    }
    reproducibility = _reproducibility(corpus)
    results["reproducibility"] = reproducibility
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_report(results), encoding="utf-8")
    REPRODUCIBILITY_PATH.write_text(
        json.dumps(reproducibility, indent=2) + "\n", encoding="utf-8"
    )
    return results


def _report(results: dict[str, object]) -> str:
    metrics = results["metrics"]
    lines = [
        "# Phase 7.1 Real-World Financial Document Evaluation",
        "",
        f"Generated: {results['generated_at']}",
        "",
        "## Scope and provenance",
        "",
        "Two official public annual-report PDFs were checksum-validated and passed through the production PyMuPDF extraction, page-aware chunking, BGE embeddings, BM25, adaptive routing/RRF, evidence verification, claim verification, citation checks, and confidence scoring.",
        "",
        "| Company | Report | PDF pages | Chunks | SHA-256 |",
        "|---|---|---:|---:|---|",
    ]
    corpus_by_id = {
        value["document_id"]: value for value in results["corpus"]["documents"]
    }
    for source in results["sources"]:
        corpus = corpus_by_id[source["document_id"]]
        lines.append(
            f"| {source['company']} | [{source['document_name']}]({source['official_landing_page']}) | {source['pdf_page_count']} | {corpus['chunks']} | `{source['sha256']}` |"
        )
    lines.extend(
        [
            "",
            "## Automatically measured results",
            "",
            f"The dataset has **{metrics['case_count']} cases**, **{metrics['category_count']} categories**, and **{metrics['company_count']} companies**.",
            "",
            "| Metric | Result |",
            "|---|---:|",
            f"| Strategy-selection accuracy | {metrics['strategy_selection_accuracy']:.3f} |",
            f"| Exact evidence-outcome accuracy | {metrics['evidence_outcome_exact_accuracy']:.3f} |",
            f"| Answerability precision / recall | {metrics['answerability_precision']:.3f} / {metrics['answerability_recall']:.3f} |",
            f"| Abstention precision / recall | {metrics['abstention_precision']:.3f} / {metrics['abstention_recall']:.3f} |",
            f"| Citation-page correctness on answerable cases | {metrics['citation_page_correctness_on_answerable_cases']:.3f} |",
            f"| Reference claims fully supported | {metrics['reference_claim_fully_supported_rate']:.3f} |",
            f"| Additional-retrieval frequency | {metrics['additional_retrieval_frequency']:.3f} |",
            f"| Mean retrieval latency | {metrics['average_retrieval_latency_ms']:.3f} ms |",
            f"| Mean verification latency | {metrics['average_verification_latency_ms']:.3f} ms |",
            f"| Mean pipeline latency without LLM | {metrics['average_end_to_end_latency_ms_without_llm']:.3f} ms |",
            "| Generated-answer correctness / LLM cost | Not measured / no LLM call |",
            "",
            "| Case | Category | Expected → observed strategy | Expected → observed evidence | Citation page | Decision |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for record in results["records"]:
        citation = (
            "n/a"
            if record["citation_page_match"] is None
            else str(record["citation_page_match"])
        )
        lines.append(
            f"| {record['case_id']} | {record['category']} | {record['expected']['strategy']} → {record['selected_retrieval_strategy']} | "
            f"{record['expected']['verification_outcome']} → {record['evidence']['status']} | {citation} | {record['final_decision']} |"
        )
    lines.extend(
        [
            "",
            "## Manual versus automatic review",
            "",
            "Expected answers, page labels, evidence excerpts, intended strategies, and intended verification outcomes in `dataset.json` were manually transcribed and reviewed against the two PDFs. Retrieval ranks, page intersections, verifier decisions, claims, confidence values, and latencies in `results.json` are automatically measured. Generated-answer correctness was not measured because LLM calls were deliberately disabled.",
            "",
            "## Environment limitations",
            "",
            "Docker Desktop was not running, so the external ChromaDB service could not be exercised. An evaluation-only exact cosine store replaced Chroma while preserving the production BGE model, `SemanticRetrievalService`, user/document filters, BM25, adaptive routing, and RRF. Consequently, this run tests semantic relevance but not Chroma HTTP behavior or approximate-index latency. No LLM provider was called.",
            "",
            "These results characterize this small, versioned dataset only. They do not establish general financial-QA accuracy or eliminate hallucination risk.",
            "",
            "## Bugs found and narrowly scoped fixes",
            "",
            "- BM25 tokenization retained question stopwords and ranking over-weighted boilerplate. Stopwords are now removed and metric/year proximity contributes to deterministic reranking.",
            "- Plural metrics such as `margins` and the financial metric `unit case volume` were not analyzed correctly. The rule-based analyzer now recognizes them.",
            "- Evidence sufficiency could accept a metric and reporting period occurring far apart in one large chunk. Metric, period, and numeric evidence must now co-occur in a bounded local window.",
            "- Unreported ratios and ambiguous terms such as bare `profit` or broad `performance` could be treated as answerable. They now require explicit ratio evidence or clarification.",
            "- Citation-only fragments after sentence punctuation were detached from the preceding claim. Claim extraction now attaches them before verification.",
            "",
            "## Remaining observed failures",
            "",
            "Manual review is recorded in `manual_review.json`. The remaining failures are retrieval of NVIDIA consolidated revenue/operating-income summary passages, exact endpoint support for the NVIDIA comparison, and retrieval of Coca-Cola's page-7 worldwide unit-case values. No dataset-specific production workaround was added. The evidence verifier can still overestimate sufficiency when a chunk contains related numeric material but not the specifically requested value; claim verification caught the evaluated combined claims.",
            "",
            "## Reproduction",
            "",
            "From `backend/` on Windows PowerShell:",
            "",
            "```powershell",
            "$env:HF_HOME = (Resolve-Path '.model-cache')",
            "$env:HF_HUB_OFFLINE = '1'",
            ".\\.venv\\Scripts\\python.exe -m app.evaluation.real_world.runner",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    results = asyncio.run(run())
    print(json.dumps(results["metrics"], indent=2))


if __name__ == "__main__":
    main()
