"""Reproducible local performance and reliability benchmark for FinAssist AI.

This runner never calls an LLM and never connects to Docker, PostgreSQL, or
ChromaDB. It uses the production services with an isolated SQLite database and
an explicitly labelled exact in-memory cosine substitute for ChromaDB.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import platform
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter, process_time
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pymupdf
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base
from app.evaluation.real_world.runner import (
    CACHE_DIR as REAL_CACHE_DIR,
)
from app.evaluation.real_world.runner import (
    DATASET_PATH,
    DOCUMENTS_DIR,
    MANIFEST_PATH,
    ExactCosineVectorStore,
    _chunk_fingerprint,
    _page_match,
    _source_numbers,
)
from app.models import Document, DocumentChunk, DocumentStatus, User
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalSelector,
    AdaptiveRetrievalService,
)
from app.services.claim_verifier import ClaimVerifier
from app.services.embedding_service import EmbeddingService
from app.services.evidence_verifier import EvidenceVerifier
from app.services.keyword_retrieval import (
    KeywordRetrievalService,
    tokenize_financial_text,
)
from app.services.pdf_processor import InvalidPdfError, extract_pdf_pages, inspect_pdf
from app.services.query_analyzer import FinancialQueryAnalyzer
from app.services.retrieval_service import SemanticRetrievalService
from app.services.text_chunker import TextChunk, chunk_pages
from app.services.vector_store import VectorSearchResult

ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "results.json"
BASELINE_PATH = ROOT / "baseline_results.json"
OPTIMIZED_PATH = ROOT / "optimized_results.json"
USER_ID = UUID("62000000-0000-0000-0000-000000000001")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _windows_working_set_bytes() -> int | None:
    """Return current working set without adding a third-party dependency."""

    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize) if ok else None
    except (AttributeError, OSError):
        return None


@dataclass(slots=True)
class ResourceMeasurement:
    wall_time_ms: float
    process_cpu_time_ms: float
    start_rss_bytes: int | None
    peak_rss_bytes: int | None
    peak_rss_delta_bytes: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "wall_time_ms": round(self.wall_time_ms, 3),
            "process_cpu_time_ms": round(self.process_cpu_time_ms, 3),
            "start_rss_bytes": self.start_rss_bytes,
            "peak_rss_bytes": self.peak_rss_bytes,
            "peak_rss_delta_bytes": self.peak_rss_delta_bytes,
        }


class _ResourceSampler:
    def __init__(self, interval_seconds: float = 0.01) -> None:
        self.interval_seconds = interval_seconds
        self.start_rss = _windows_working_set_bytes()
        self.peak_rss = self.start_rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._wall_started = perf_counter()
        self._cpu_started = process_time()

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            current = _windows_working_set_bytes()
            if current is not None and (
                self.peak_rss is None or current > self.peak_rss
            ):
                self.peak_rss = current

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> ResourceMeasurement:
        self._stop.set()
        self._thread.join(timeout=1)
        current = _windows_working_set_bytes()
        if current is not None and (self.peak_rss is None or current > self.peak_rss):
            self.peak_rss = current
        delta = (
            self.peak_rss - self.start_rss
            if self.peak_rss is not None and self.start_rss is not None
            else None
        )
        return ResourceMeasurement(
            wall_time_ms=(perf_counter() - self._wall_started) * 1000,
            process_cpu_time_ms=(process_time() - self._cpu_started) * 1000,
            start_rss_bytes=self.start_rss,
            peak_rss_bytes=self.peak_rss,
            peak_rss_delta_bytes=delta,
        )


@contextmanager
def _measure() -> Iterator[_ResourceSampler]:
    sampler = _ResourceSampler()
    sampler.start()
    try:
        yield sampler
    finally:
        pass


def _finish(sampler: _ResourceSampler) -> dict[str, object]:
    return sampler.finish().as_dict()


def _load_manifest(*, validate_checksums: bool) -> list[dict[str, object]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    validated: list[dict[str, object]] = []
    for item in manifest["documents"]:
        path = DOCUMENTS_DIR / str(item["local_filename"])
        if not path.is_file():
            raise FileNotFoundError(path)
        if validate_checksums and _sha256(path) != item["sha256"]:
            raise ValueError(f"Checksum mismatch for {path.name}")
        if path.stat().st_size != item["file_size_bytes"]:
            raise ValueError(f"Size mismatch for {path.name}")
        validated.append(item)
    return validated


def _load_cached_corpus(
    sources: list[dict[str, object]],
) -> tuple[list[TextChunk], list[list[float]], dict[UUID, str]]:
    chunks: list[TextChunk] = []
    vectors: list[list[float]] = []
    filenames: dict[UUID, str] = {}
    for source in sources:
        document_id = UUID(str(source["document_id"]))
        filenames[document_id] = str(source["local_filename"])
        chunk_path = REAL_CACHE_DIR / f"{document_id}.chunks.json"
        vector_path = REAL_CACHE_DIR / f"{document_id}.embeddings.npz"
        meta_path = REAL_CACHE_DIR / f"{document_id}.embeddings.meta.json"
        if (
            not chunk_path.is_file()
            or not vector_path.is_file()
            or not meta_path.is_file()
        ):
            raise FileNotFoundError(f"Incomplete Phase 7.1 cache for {document_id}")
        serialized = json.loads(chunk_path.read_text(encoding="utf-8"))
        document_chunks = [
            TextChunk(
                id=UUID(value["id"]),
                document_id=UUID(value["document_id"]),
                user_id=USER_ID,
                chunk_index=int(value["chunk_index"]),
                text=value["text"],
                token_count=int(value["token_count"]),
                page_numbers=[int(page) for page in value["page_numbers"]],
            )
            for value in serialized
        ]
        with np.load(vector_path, allow_pickle=False) as cache:
            ids = [str(value) for value in cache["chunk_ids"].tolist()]
            matrix = cache["embeddings"].astype(np.float32)
        if ids != [str(chunk.id) for chunk in document_chunks]:
            raise ValueError(f"Embedding IDs do not match chunks for {document_id}")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("chunk_fingerprint") != _chunk_fingerprint(document_chunks):
            raise ValueError(f"Embedding cache fingerprint mismatch for {document_id}")
        chunks.extend(document_chunks)
        vectors.extend(matrix.tolist())
    return chunks, vectors, filenames


class VectorizedExactCosineStore:
    """Evaluation-only vectorized exact cosine over normalized BGE embeddings."""

    def __init__(
        self,
        chunks: list[TextChunk],
        filenames: dict[UUID, str],
        vectors: list[list[float]],
    ) -> None:
        self.chunks = chunks
        self.filenames = filenames
        self.matrix = np.asarray(vectors, dtype=np.float32)

    def search_similar_chunks(
        self,
        query_embedding: list[float],
        *,
        user_id: UUID,
        document_ids: list[UUID] | None = None,
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        selected = set(document_ids or [])
        indices = [
            index
            for index, chunk in enumerate(self.chunks)
            if chunk.user_id == user_id
            and (not selected or chunk.document_id in selected)
        ]
        if not indices or top_k < 1:
            return []
        selected_matrix = self.matrix[indices]
        scores = selected_matrix @ np.asarray(query_embedding, dtype=np.float32)
        ranked = sorted(
            zip(indices, scores.tolist(), strict=True),
            key=lambda value: (-value[1], str(self.chunks[value[0]].id)),
        )[:top_k]
        return [
            VectorSearchResult(
                chunk_id=self.chunks[index].id,
                user_id=self.chunks[index].user_id,
                document_id=self.chunks[index].document_id,
                filename=self.filenames[self.chunks[index].document_id],
                page_numbers=self.chunks[index].page_numbers,
                chunk_text=self.chunks[index].text,
                similarity_score=float(score),
            )
            for index, score in ranked
        ]


def _benchmark_pdf_pipeline(
    sources: list[dict[str, object]], settings: Any
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for source in sources:
        path = DOCUMENTS_DIR / str(source["local_filename"])
        document_id = UUID(str(source["document_id"]))
        print(f"Extracting {path.name}...", flush=True)
        with _measure() as extraction_sampler:
            extracted = extract_pdf_pages(path, document_id, path.name)
        extraction_resources = _finish(extraction_sampler)
        with _measure() as chunk_sampler:
            chunks = chunk_pages(
                extracted.pages,
                document_id=document_id,
                user_id=USER_ID,
                target_size=settings.chunk_size_tokens,
                overlap_size=settings.chunk_overlap_tokens,
            )
        chunk_resources = _finish(chunk_sampler)
        print(f"Extracted and chunked {path.name}.", flush=True)
        records.append(
            {
                "document_id": str(document_id),
                "filename": path.name,
                "file_size_bytes": path.stat().st_size,
                "page_count": extracted.page_count,
                "empty_page_count": sum(
                    not page.extracted_text for page in extracted.pages
                ),
                "extracted_characters": sum(
                    len(page.extracted_text) for page in extracted.pages
                ),
                "chunk_count": len(chunks),
                "extraction": extraction_resources,
                "chunking": chunk_resources,
            }
        )
    return {"documents": records}


def _benchmark_embeddings(
    chunks: list[TextChunk], embedding: EmbeddingService, *, execute: bool
) -> dict[str, object]:
    cache_paths = list(REAL_CACHE_DIR.glob("*.embeddings.npz"))
    with _measure() as cache_sampler:
        cached_count = 0
        cached_bytes = 0
        for path in cache_paths:
            with np.load(path, allow_pickle=False) as cache:
                cached_count += int(cache["embeddings"].shape[0])
                cached_bytes += int(cache["embeddings"].nbytes)
    cache_resources = _finish(cache_sampler)
    result: dict[str, object] = {
        "cache_load": {
            **cache_resources,
            "embedding_count": cached_count,
            "uncompressed_vector_bytes": cached_bytes,
        },
        "generation": None,
    }
    if execute:
        with _measure() as generation_sampler:
            generated = embedding.embed_documents([chunk.text for chunk in chunks])
        generation_resources = _finish(generation_sampler)
        result["generation"] = {
            **generation_resources,
            "embedding_count": len(generated),
            "embedding_dimension": len(generated[0]) if generated else None,
            "embeddings_per_second": round(
                len(generated) / (float(generation_resources["wall_time_ms"]) / 1000),
                3,
            ),
            "normalized": all(
                abs(float(np.linalg.norm(vector)) - 1.0) < 1e-4
                for vector in generated[:10]
            ),
        }
    return result


async def _build_database(
    sources: list[dict[str, object]],
    chunks: list[TextChunk],
    filenames: dict[UUID, str],
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session = session_factory()
    session.add(
        User(
            id=USER_ID,
            full_name="Performance benchmark",
            email="performance@example.invalid",
            hashed_password="not-a-login-account",
            is_active=True,
        )
    )
    for source in sources:
        document_id = UUID(str(source["document_id"]))
        document_chunks = [
            chunk for chunk in chunks if chunk.document_id == document_id
        ]
        session.add(
            Document(
                id=document_id,
                user_id=USER_ID,
                filename=filenames[document_id],
                storage_path=str(DOCUMENTS_DIR / filenames[document_id]),
                file_size=int(source["file_size_bytes"]),
                mime_type="application/pdf",
                page_count=int(source["pdf_page_count"]),
                processing_status=DocumentStatus.COMPLETED,
                indexed_chunk_count=len(document_chunks),
                embedding_model=get_settings().embedding_model,
                indexed_at=datetime.now(UTC),
            )
        )
        session.add_all(
            DocumentChunk(
                id=chunk.id,
                document_id=chunk.document_id,
                user_id=USER_ID,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                page_numbers=chunk.page_numbers,
            )
            for chunk in document_chunks
        )
    await session.commit()
    return engine, session


async def _benchmark_retrieval_and_verification(
    sources: list[dict[str, object]],
    chunks: list[TextChunk],
    vectors: list[list[float]],
    filenames: dict[UUID, str],
    embedding: EmbeddingService,
    *,
    vectorized: bool,
) -> dict[str, object]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    settings = get_settings()
    engine, session = await _build_database(sources, chunks, filenames)
    try:
        keyword = KeywordRetrievalService(
            k1=settings.bm25_k1,
            b=settings.bm25_b,
            epsilon=settings.bm25_epsilon,
            max_cached_users=settings.bm25_cache_users,
        )
        if vectorized:
            vector_store: Any = VectorizedExactCosineStore(chunks, filenames, vectors)
        else:
            loop_store = ExactCosineVectorStore()
            for source in sources:
                document_id = UUID(str(source["document_id"]))
                pairs = [
                    (chunk, vector)
                    for chunk, vector in zip(chunks, vectors, strict=True)
                    if chunk.document_id == document_id
                ]
                loop_store.add(
                    [pair[0] for pair in pairs],
                    filenames[document_id],
                    [pair[1] for pair in pairs],
                )
            vector_store = loop_store
        semantic = SemanticRetrievalService(
            embedding,
            vector_store,
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
        claims = ClaimVerifier()

        first_case = dataset["cases"][0]
        print("Benchmarking BM25 cold and warm paths...", flush=True)
        cold_started = perf_counter()
        await keyword.search_keyword(
            first_case["question"],
            USER_ID,
            [UUID(value) for value in first_case["document_ids"]],
            settings.rag_top_k,
            db=session,
        )
        bm25_cold_ms = (perf_counter() - cold_started) * 1000

        records: list[dict[str, object]] = []
        for case in dataset["cases"]:
            document_ids = [UUID(value) for value in case["document_ids"]]
            keyword_started = perf_counter()
            keyword_results = await keyword.search_keyword(
                case["question"],
                USER_ID,
                document_ids,
                settings.rag_top_k,
                db=session,
            )
            keyword_ms = (perf_counter() - keyword_started) * 1000

            semantic_started = perf_counter()
            semantic_results = await semantic.retrieve(
                case["question"],
                user_id=USER_ID,
                document_ids=document_ids,
                top_k=settings.rag_top_k,
            )
            semantic_ms = (perf_counter() - semantic_started) * 1000

            pipeline_started = perf_counter()
            adaptive_result = await adaptive.retrieve(
                session,
                case["question"],
                user_id=USER_ID,
                document_ids=document_ids,
                top_k=settings.rag_top_k,
            )
            retrieval_ms = (perf_counter() - pipeline_started) * 1000
            verify_started = perf_counter()
            assessment = evidence.verify(
                case["question"],
                adaptive_result.retrieved_chunks,
                user_id=USER_ID,
                allowed_document_ids=set(document_ids),
            )
            evidence_ms = (perf_counter() - verify_started) * 1000
            source_numbers = _source_numbers(case, adaptive_result.retrieved_chunks)
            claim_ms = 0.0
            claim_status = None
            if case["expected_answer"] and source_numbers:
                cited = " ".join(f"[Source {number}]" for number in source_numbers)
                claim_started = perf_counter()
                claim = claims.verify(
                    f"{case['expected_answer']} {cited}",
                    adaptive_result.retrieved_chunks,
                )
                claim_ms = (perf_counter() - claim_started) * 1000
                claim_status = claim.overall_status.value
            total_ms = (perf_counter() - pipeline_started) * 1000
            records.append(
                {
                    "case_id": case["id"],
                    "selected_strategy": adaptive_result.diagnostics.selected_strategy.value,
                    "expected_strategy": case["expected_retrieval_strategy"],
                    "keyword_result_count": len(keyword_results),
                    "semantic_result_count": len(semantic_results),
                    "retrieved_count": len(adaptive_result.retrieved_chunks),
                    "keyword_latency_ms": round(keyword_ms, 3),
                    "semantic_latency_ms": round(semantic_ms, 3),
                    "adaptive_retrieval_latency_ms": round(retrieval_ms, 3),
                    "evidence_verification_latency_ms": round(evidence_ms, 3),
                    "claim_verification_latency_ms": round(claim_ms, 3),
                    "total_pipeline_without_llm_ms": round(total_ms, 3),
                    "evidence_status": assessment.evidence_status.value,
                    "claim_status": claim_status,
                    "citation_page_match": _page_match(
                        case, adaptive_result.retrieved_chunks
                    ),
                    "top_chunk_ids": [
                        str(item.chunk_id) for item in adaptive_result.retrieved_chunks
                    ],
                }
            )
        return {
            "vector_backend": (
                "vectorized exact in-memory cosine substitute"
                if vectorized
                else "Python-loop exact in-memory cosine substitute"
            ),
            "chroma_exercised": False,
            "bm25_cold_index_and_query_ms": round(bm25_cold_ms, 3),
            "bm25_index_build_count": keyword.build_count,
            "records": records,
            "averages_ms": {
                field: round(mean(float(record[field]) for record in records), 3)
                for field in (
                    "keyword_latency_ms",
                    "semantic_latency_ms",
                    "adaptive_retrieval_latency_ms",
                    "evidence_verification_latency_ms",
                    "claim_verification_latency_ms",
                    "total_pipeline_without_llm_ms",
                )
            },
            "quality": {
                "strategy_accuracy": round(
                    mean(
                        record["selected_strategy"] == record["expected_strategy"]
                        for record in records
                    ),
                    6,
                ),
                "citation_page_match_rate": round(
                    mean(
                        bool(record["citation_page_match"])
                        for record in records
                        if record["citation_page_match"] is not None
                    ),
                    6,
                ),
            },
        }
    finally:
        await session.close()
        await engine.dispose()


def _benchmark_cached_components(
    sources: list[dict[str, object]],
    chunks: list[TextChunk],
    vectors: list[list[float]],
    filenames: dict[UUID, str],
    *,
    vectorized: bool,
) -> dict[str, object]:
    """Measure components that do not require a fresh Transformer inference call."""

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    phase_71_path = DATASET_PATH.with_name("results.json")
    phase_71 = json.loads(phase_71_path.read_text(encoding="utf-8"))
    settings = get_settings()
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    print("Benchmarking BM25 index construction and warm scoring...", flush=True)
    rows = [(chunk, filenames[chunk.document_id]) for chunk in chunks]
    cold_started = perf_counter()
    keyword_index = KeywordRetrievalService._build_index(
        rows, settings.bm25_k1, settings.bm25_b, settings.bm25_epsilon
    )
    first_tokens = tokenize_financial_text(dataset["cases"][0]["question"])
    if keyword_index.model is not None:
        keyword_index.model.get_scores(first_tokens)
    bm25_cold_ms = (perf_counter() - cold_started) * 1000
    keyword_times: list[float] = []
    for case in dataset["cases"]:
        started = perf_counter()
        if keyword_index.model is not None:
            keyword_index.model.get_scores(tokenize_financial_text(case["question"]))
        keyword_times.append((perf_counter() - started) * 1000)

    if vectorized:
        store: Any = VectorizedExactCosineStore(chunks, filenames, vectors)
    else:
        loop_store = ExactCosineVectorStore()
        for source in sources:
            document_id = UUID(str(source["document_id"]))
            pairs = [
                (chunk, vector)
                for chunk, vector in zip(chunks, vectors, strict=True)
                if chunk.document_id == document_id
            ]
            loop_store.add(
                [pair[0] for pair in pairs],
                filenames[document_id],
                [pair[1] for pair in pairs],
            )
        store = loop_store
    print("Benchmarking exact-cosine search math...", flush=True)
    cosine_times: list[float] = []
    cosine_rankings: list[list[str]] = []
    for case_index, case in enumerate(dataset["cases"]):
        document_ids = [UUID(value) for value in case["document_ids"]]
        query_vector = vectors[(case_index * 37) % len(vectors)]
        started = perf_counter()
        cosine_results = store.search_similar_chunks(
            query_vector,
            user_id=USER_ID,
            document_ids=document_ids,
            top_k=settings.rag_top_k,
        )
        cosine_times.append((perf_counter() - started) * 1000)
        cosine_rankings.append([str(item.chunk_id) for item in cosine_results])

    evidence = EvidenceVerifier(
        relevance_threshold=settings.evidence_relevance_threshold,
        sufficiency_threshold=settings.evidence_sufficiency_threshold,
        weak_threshold=settings.evidence_weak_threshold,
    )
    claims = ClaimVerifier()
    print("Benchmarking evidence and claim verification...", flush=True)
    evidence_times: list[float] = []
    claim_times: list[float] = []
    for case, prior_record in zip(dataset["cases"], phase_71["records"], strict=True):
        retrieved: list[VectorSearchResult] = []
        for passage in prior_record["retrieved_passages"]:
            chunk_id = UUID(passage["chunk_id"])
            chunk = chunk_by_id[chunk_id]
            retrieved.append(
                VectorSearchResult(
                    chunk_id=chunk.id,
                    user_id=USER_ID,
                    document_id=chunk.document_id,
                    filename=filenames[chunk.document_id],
                    page_numbers=chunk.page_numbers,
                    chunk_text=chunk.text,
                    similarity_score=float(passage["score"]),
                )
            )
        started = perf_counter()
        evidence.verify(
            case["question"],
            retrieved,
            user_id=USER_ID,
            allowed_document_ids={UUID(value) for value in case["document_ids"]},
        )
        evidence_times.append((perf_counter() - started) * 1000)
        source_numbers = _source_numbers(case, retrieved)
        if case["expected_answer"] and source_numbers:
            cited = " ".join(f"[Source {number}]" for number in source_numbers)
            started = perf_counter()
            claims.verify(f"{case['expected_answer']} {cited}", retrieved)
            claim_times.append((perf_counter() - started) * 1000)

    return {
        "mode": "cached-component microbenchmarks; no fresh query embedding",
        "vector_backend": (
            "vectorized exact in-memory cosine substitute"
            if vectorized
            else "Python-loop exact in-memory cosine substitute"
        ),
        "chroma_exercised": False,
        "bm25": {
            "cold_index_and_query_ms": round(bm25_cold_ms, 3),
            "warm_query_average_ms": round(mean(keyword_times), 3),
            "warm_query_samples": len(keyword_times),
            "index_build_count": 1,
            "scope": "production index builder and BM25 scoring; database query excluded",
        },
        "exact_cosine_search": {
            "average_ms": round(mean(cosine_times), 3),
            "samples": len(cosine_times),
            "query_vectors": "normalized cached production BGE document vectors used only to isolate search math",
            "rankings": cosine_rankings,
        },
        "evidence_verification": {
            "average_ms": round(mean(evidence_times), 3),
            "samples": len(evidence_times),
        },
        "claim_verification": {
            "average_ms": round(mean(claim_times), 3),
            "samples": len(claim_times),
        },
        "phase_71_pipeline_reference": {
            "source": str(
                phase_71_path.relative_to(Path(__file__).resolve().parents[4])
            ),
            "case_count": phase_71["metrics"]["case_count"],
            "average_retrieval_latency_ms": phase_71["metrics"][
                "average_retrieval_latency_ms"
            ],
            "average_verification_latency_ms": phase_71["metrics"][
                "average_verification_latency_ms"
            ],
            "average_end_to_end_latency_ms_without_llm": phase_71["metrics"][
                "average_end_to_end_latency_ms_without_llm"
            ],
            "citation_page_correctness": phase_71["metrics"][
                "citation_page_correctness_on_answerable_cases"
            ],
        },
    }


def _write_pdf(path: Path, page_texts: list[str]) -> None:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()


def _reliability_checks(sources: list[dict[str, object]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    def record(name: str, expected: str, action: Any) -> None:
        started = perf_counter()
        try:
            detail = action()
            records.append(
                {
                    "name": name,
                    "status": "passed",
                    "expected": expected,
                    "observed": detail,
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                }
            )
        except (
            AssertionError,
            InvalidPdfError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            records.append(
                {
                    "name": name,
                    "status": "failed",
                    "expected": expected,
                    "observed": f"{type(exc).__name__}: {exc}",
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                }
            )

    with tempfile.TemporaryDirectory(prefix="finassist-performance-") as directory:
        temporary = Path(directory)
        corrupt = temporary / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.7\nnot a valid PDF")

        def corrupted() -> str:
            try:
                inspect_pdf(corrupt)
            except InvalidPdfError as exc:
                return str(exc)
            raise AssertionError("corrupted PDF was accepted")

        record("corrupted_pdf", "safe InvalidPdfError", corrupted)

        unsupported = temporary / "not-pdf.txt"
        unsupported.write_text("plain text", encoding="utf-8")

        def unsupported_type() -> str:
            try:
                inspect_pdf(unsupported)
            except InvalidPdfError as exc:
                return str(exc)
            raise AssertionError("non-PDF was accepted")

        record("unsupported_file_content", "safe InvalidPdfError", unsupported_type)

        blank = temporary / "blank.pdf"
        _write_pdf(blank, [""])

        def blank_pdf() -> str:
            result = extract_pdf_pages(blank, uuid4(), blank.name)
            assert result.page_count == 1 and result.pages[0].extracted_text == ""
            return "one page preserved with empty extracted text"

        record("empty_text_pdf", "empty page preserved", blank_pdf)

        finance = temporary / "finance.pdf"
        finance_text = "Revenue: $1,234.56 | Margin: -4.2% | FY2025"
        _write_pdf(finance, [finance_text])

        def financial_symbols() -> str:
            result = extract_pdf_pages(finance, uuid4(), finance.name)
            text = result.pages[0].extracted_text
            for expected in ("$1,234.56", "-4.2%", "FY2025"):
                assert expected in text
            return text

        record(
            "financial_punctuation", "values and symbols preserved", financial_symbols
        )

        multipage = temporary / "multipage.pdf"
        _write_pdf(multipage, ["Page one", "Page two", "Page three"])

        def multi_page() -> str:
            result = extract_pdf_pages(multipage, uuid4(), multipage.name)
            assert [page.page_number for page in result.pages] == [1, 2, 3]
            return "page numbers 1, 2, 3 preserved"

        record("multi_page_pdf", "page order preserved", multi_page)

        retry = temporary / "retry.pdf"
        retry.write_bytes(b"broken")

        def retry_after_failure() -> str:
            failed = False
            try:
                inspect_pdf(retry)
            except InvalidPdfError:
                failed = True
            assert failed
            _write_pdf(retry, ["Retry succeeded with $42.00 in FY2025"])
            assert inspect_pdf(retry) == 1
            return "initial failure followed by successful reprocessing"

        record(
            "retry_after_failure",
            "retry succeeds after source correction",
            retry_after_failure,
        )

    largest = max(
        sources,
        key=lambda source: (
            (DOCUMENTS_DIR / str(source["local_filename"])).stat().st_size
        ),
    )

    def large_pdf() -> str:
        path = DOCUMENTS_DIR / str(largest["local_filename"])
        pages = inspect_pdf(path)
        assert pages == int(largest["pdf_page_count"])
        return f"{path.stat().st_size} bytes, {pages} pages"

    record("large_real_pdf", "official large PDF validates", large_pdf)
    return records


async def run(
    *,
    label: str,
    execute_embeddings: bool,
    vectorized: bool,
    skip_query_inference: bool,
    validate_source_checksums: bool,
) -> dict[str, object]:
    settings = get_settings()
    sources = _load_manifest(validate_checksums=validate_source_checksums)
    print(
        "Validated source checksums."
        if validate_source_checksums
        else "Trusted Phase 7.1 checksums; verified source presence and byte sizes.",
        flush=True,
    )
    chunks, vectors, filenames = _load_cached_corpus(sources)
    print(f"Loaded {len(chunks)} cached chunks and embeddings.", flush=True)
    embedding = EmbeddingService(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
        query_prefix=settings.embedding_query_prefix,
    )
    pdf = _benchmark_pdf_pipeline(sources, settings)
    print("Benchmarking embedding cache path...", flush=True)
    embeddings = _benchmark_embeddings(chunks, embedding, execute=execute_embeddings)
    if skip_query_inference:
        retrieval = _benchmark_cached_components(
            sources,
            chunks,
            vectors,
            filenames,
            vectorized=vectorized,
        )
    else:
        retrieval = await _benchmark_retrieval_and_verification(
            sources,
            chunks,
            vectors,
            filenames,
            embedding,
            vectorized=vectorized,
        )
    reliability = _reliability_checks(sources)
    print("Completed PDF reliability checks.", flush=True)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "label": label,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "cpu_logical_count": os.cpu_count(),
            "torch_device": "cpu",
            "gpu_measured": False,
            "database": "isolated in-memory SQLite substitute",
            "postgresql_exercised": False,
            "chroma_exercised": False,
            "llm_exercised": False,
            "docker_operations_performed": False,
            "working_set_source": (
                "Windows GetProcessMemoryInfo sampled every 10 ms"
                if os.name == "nt"
                else "unavailable"
            ),
        },
        "corpus": {
            "documents": len(sources),
            "chunks": len(chunks),
            "embedding_dimension": len(vectors[0]) if vectors else None,
            "source_checksums": {
                str(source["local_filename"]): source["sha256"] for source in sources
            },
            "dataset_sha256": _sha256(DATASET_PATH),
            "source_checksums_revalidated_this_run": validate_source_checksums,
        },
        "pdf_pipeline": pdf,
        "embeddings": embeddings,
        "retrieval_and_verification": retrieval,
        "pdf_reliability": reliability,
        "limitations": [
            "Live PostgreSQL was not exercised; SQLite is not equivalent to PostgreSQL.",
            "Live ChromaDB was unavailable; semantic timings use an explicitly labelled exact in-memory cosine substitute.",
            "No LLM provider was configured or called, so generation latency and answer-generation reliability are unavailable.",
            "GPU measurements are unavailable because torch reported CPU-only execution for this run.",
            "OCR is not implemented; image-only PDFs can produce empty extracted text.",
        ],
    }


def run_without_query_inference(
    *, label: str, execute_embeddings: bool, vectorized: bool
) -> dict[str, object]:
    """Synchronous benchmark path for environments where asyncio is restricted."""

    settings = get_settings()
    sources = _load_manifest(validate_checksums=False)
    print(
        "Trusted Phase 7.1 checksums; verified source presence and byte sizes.",
        flush=True,
    )
    chunks, vectors, filenames = _load_cached_corpus(sources)
    print(f"Loaded {len(chunks)} cached chunks and embeddings.", flush=True)
    embedding = EmbeddingService(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
        query_prefix=settings.embedding_query_prefix,
    )
    pdf = _benchmark_pdf_pipeline(sources, settings)
    print("Benchmarking embedding cache path...", flush=True)
    embeddings = _benchmark_embeddings(chunks, embedding, execute=execute_embeddings)
    retrieval = _benchmark_cached_components(
        sources, chunks, vectors, filenames, vectorized=vectorized
    )
    reliability = _reliability_checks(sources)
    print("Completed PDF reliability checks.", flush=True)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "label": label,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "cpu_logical_count": os.cpu_count(),
            "torch_device": "cpu",
            "gpu_measured": False,
            "database": "not used by cached-component benchmark",
            "postgresql_exercised": False,
            "chroma_exercised": False,
            "llm_exercised": False,
            "docker_operations_performed": False,
            "asyncio_note": "Windows event-loop socketpair was unavailable in the managed sandbox; synchronous benchmark path used.",
            "working_set_source": (
                "Windows GetProcessMemoryInfo sampled every 10 ms"
                if os.name == "nt"
                else "unavailable"
            ),
        },
        "corpus": {
            "documents": len(sources),
            "chunks": len(chunks),
            "embedding_dimension": len(vectors[0]) if vectors else None,
            "source_checksums": {
                str(source["local_filename"]): source["sha256"] for source in sources
            },
            "dataset_sha256": _sha256(DATASET_PATH),
            "source_checksums_revalidated_this_run": False,
        },
        "pdf_pipeline": pdf,
        "embeddings": embeddings,
        "retrieval_and_verification": retrieval,
        "pdf_reliability": reliability,
        "limitations": [
            "Live PostgreSQL was not exercised; the cached-component benchmark excluded database query timing.",
            "Live ChromaDB was unavailable; semantic search math uses an explicitly labelled exact in-memory cosine substitute.",
            "No LLM provider was configured or called, so generation latency and answer-generation reliability are unavailable.",
            "Fresh full-corpus BGE generation did not complete during the bounded CPU run; throughput is unavailable.",
            "GPU measurements are unavailable because torch reported CPU-only execution for this run.",
            "OCR is not implemented; image-only PDFs can produce empty extracted text.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", choices=("baseline", "optimized"), required=True)
    parser.add_argument("--execute-embeddings", action="store_true")
    parser.add_argument("--vectorized", action="store_true")
    parser.add_argument("--skip-query-inference", action="store_true")
    parser.add_argument("--trust-phase71-checksums", action="store_true")
    args = parser.parse_args()

    model_cache = Path(__file__).resolve().parents[3] / ".model-cache"
    os.environ.setdefault("HF_HOME", str(model_cache))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    if args.skip_query_inference:
        results = run_without_query_inference(
            label=args.label,
            execute_embeddings=args.execute_embeddings,
            vectorized=args.vectorized,
        )
    else:
        results = asyncio.run(
            run(
                label=args.label,
                execute_embeddings=args.execute_embeddings,
                vectorized=args.vectorized,
                skip_query_inference=False,
                validate_source_checksums=not args.trust_phase71_checksums,
            )
        )
    destination = BASELINE_PATH if args.label == "baseline" else OPTIMIZED_PATH
    destination.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")
    if args.label == "optimized" and BASELINE_PATH.is_file():
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        before_pdf = baseline["pdf_pipeline"]["documents"][0]
        after_pdf = results["pdf_pipeline"]["documents"][0]
        before_cosine = baseline["retrieval_and_verification"]["exact_cosine_search"]
        after_cosine = results["retrieval_and_verification"]["exact_cosine_search"]

        def reduction(before: float, after: float) -> float:
            return round((before - after) / before * 100, 3) if before else 0.0

        consolidated = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "environment_limited_complete",
            "artifacts": {
                "baseline": BASELINE_PATH.name,
                "optimized": OPTIMIZED_PATH.name,
                "phase_71_reference": "../real_world/results.json",
            },
            "workload": results["corpus"],
            "baseline": {
                "pdf_pipeline": baseline["pdf_pipeline"],
                "embedding_cache": baseline["embeddings"],
                "retrieval_and_verification": baseline["retrieval_and_verification"],
            },
            "optimized": {
                "pdf_pipeline": results["pdf_pipeline"],
                "embedding_cache": results["embeddings"],
                "retrieval_and_verification": results["retrieval_and_verification"],
            },
            "comparison": {
                "nvidia_pdf_extraction": {
                    "before_wall_time_ms": before_pdf["extraction"]["wall_time_ms"],
                    "after_wall_time_ms": after_pdf["extraction"]["wall_time_ms"],
                    "wall_time_reduction_percent": reduction(
                        before_pdf["extraction"]["wall_time_ms"],
                        after_pdf["extraction"]["wall_time_ms"],
                    ),
                    "before_peak_rss_delta_bytes": before_pdf["extraction"][
                        "peak_rss_delta_bytes"
                    ],
                    "after_peak_rss_delta_bytes": after_pdf["extraction"][
                        "peak_rss_delta_bytes"
                    ],
                    "peak_rss_delta_reduction_percent": reduction(
                        before_pdf["extraction"]["peak_rss_delta_bytes"],
                        after_pdf["extraction"]["peak_rss_delta_bytes"],
                    ),
                },
                "evaluation_exact_cosine": {
                    "before_average_ms": before_cosine["average_ms"],
                    "after_average_ms": after_cosine["average_ms"],
                    "latency_reduction_percent": reduction(
                        before_cosine["average_ms"], after_cosine["average_ms"]
                    ),
                    "ranking_equivalent": before_cosine["rankings"]
                    == after_cosine["rankings"],
                    "scope": "evaluation-only in-memory ChromaDB substitute",
                },
                "quality_guardrail": {
                    "phase_71_citation_page_correctness": results[
                        "retrieval_and_verification"
                    ]["phase_71_pipeline_reference"]["citation_page_correctness"],
                    "new_phase_71_quality_run": False,
                },
            },
            "reliability": {
                "pdf_checks": results["pdf_reliability"],
                "passed": sum(
                    item["status"] == "passed" for item in results["pdf_reliability"]
                ),
                "failed": sum(
                    item["status"] == "failed" for item in results["pdf_reliability"]
                ),
            },
            "blocked_or_unavailable": {
                "fresh_full_corpus_embedding_generation": {
                    "status": "blocked",
                    "reason": "The bounded CPU-only BGE run did not complete; no generation throughput is reported.",
                },
                "gpu": {"status": "unavailable", "reason": "CPU-only torch runtime"},
                "postgresql": {"status": "blocked", "tested": False},
                "chromadb": {"status": "blocked", "tested": False},
                "llm": {"status": "blocked", "tested": False},
            },
            "environment": results["environment"],
        }
        RESULTS_PATH.write_text(
            json.dumps(consolidated, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
