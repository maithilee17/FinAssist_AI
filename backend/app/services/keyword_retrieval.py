"""Cached, user-isolated BM25 retrieval over relational document chunks."""

from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from threading import RLock
from uuid import UUID

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.services.vector_store import VectorSearchResult

_TOKEN_PATTERN = re.compile(
    r"(?:fy\s*[-']?\s*)?(?:19|20)\d{2}|\(?-?\d[\d,]*(?:\.\d+)?%?\)?|[a-z]+(?:[-'][a-z]+)*|[$€£₹¥]",
    re.IGNORECASE,
)
_CURRENCY_NAMES = {"$": "usd", "€": "eur", "£": "gbp", "₹": "inr", "¥": "yen"}
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "its",
    "of",
    "s",
    "the",
    "to",
    "was",
    "were",
    "what",
    "which",
    "with",
}
_FINANCIAL_RANK_TERMS = {
    "assets",
    "capital",
    "cash",
    "debt",
    "dividend",
    "earnings",
    "ebit",
    "ebitda",
    "eps",
    "equity",
    "expenses",
    "flow",
    "gross",
    "income",
    "liabilities",
    "margin",
    "net",
    "operating",
    "profit",
    "revenue",
    "roa",
    "roe",
    "sales",
    "unit",
    "volume",
}


def _critical_query_tokens(tokens: list[str]) -> set[str]:
    return {
        token
        for token in tokens
        if token in _FINANCIAL_RANK_TERMS
        or token.removesuffix("s") in _FINANCIAL_RANK_TERMS
        or re.fullmatch(r"(?:fy)?(?:19|20)\d{2}", token)
        or re.fullmatch(r"-?\d[\d.]*%?", token)
    }


def _critical_token_span(tokens: list[str], required: set[str]) -> int | None:
    """Return the shortest token window containing every critical query token."""

    if not required:
        return None
    positions = [
        (index, token) for index, token in enumerate(tokens) if token in required
    ]
    counts: dict[str, int] = {}
    covered = 0
    left = 0
    best: int | None = None
    for right, (right_position, token) in enumerate(positions):
        counts[token] = counts.get(token, 0) + 1
        if counts[token] == 1:
            covered += 1
        while covered == len(required):
            left_position, left_token = positions[left]
            width = right_position - left_position + 1
            best = width if best is None else min(best, width)
            counts[left_token] -= 1
            if counts[left_token] == 0:
                covered -= 1
            left += 1
    return best


def tokenize_financial_text(text: str) -> list[str]:
    from app.services.financial_table_extractor import decode_table_chunk, render_table

    if table := decode_table_chunk(text):
        text = render_table(table)
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = re.sub(
        r"\(\s*([$€£₹¥])?\s*(\d[\d,]*(?:\.\d+)?%?)\s*\)",
        lambda match: f"{match.group(1) or ''}-{match.group(2)}",
        normalized,
    )
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        token = re.sub(r"\s+", "", match.group(0))
        if token in _QUERY_STOPWORDS:
            continue
        tokens.append(token)
        if token in _CURRENCY_NAMES:
            tokens.append(_CURRENCY_NAMES[token])
        if re.match(r"^\(?-?\d", token):
            compact = token.replace(",", "").strip("()")
            if compact != token:
                tokens.append(compact)
        if "-" in token or "'" in token:
            tokens.extend(part for part in re.split(r"[-']", token) if part)
    return tokens


@dataclass(frozen=True, slots=True)
class _CorpusItem:
    result: VectorSearchResult
    tokens: list[str]


@dataclass(frozen=True, slots=True)
class _CachedIndex:
    items: list[_CorpusItem]
    model: BM25Okapi | None


class KeywordRetrievalService:
    def __init__(
        self,
        *,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
        max_cached_users: int = 128,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.max_cached_users = max_cached_users
        self._cache: OrderedDict[UUID, _CachedIndex] = OrderedDict()
        self._versions: dict[UUID, int] = {}
        self._lock = RLock()
        self.build_count = 0

    def invalidate_user(self, user_id: UUID) -> None:
        with self._lock:
            self._versions[user_id] = self._versions.get(user_id, 0) + 1
            self._cache.pop(user_id, None)

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    @staticmethod
    def _build_index(
        rows: list[tuple[DocumentChunk, str]], k1: float, b: float, epsilon: float
    ) -> _CachedIndex:
        items = [
            _CorpusItem(
                result=VectorSearchResult(
                    chunk_id=chunk.id,
                    user_id=chunk.user_id,
                    document_id=chunk.document_id,
                    filename=filename,
                    page_numbers=list(chunk.page_numbers),
                    chunk_text=chunk.text,
                    similarity_score=0.0,
                ),
                tokens=tokenize_financial_text(chunk.text),
            )
            for chunk, filename in rows
            if chunk.text.strip()
        ]
        tokenized = [item.tokens for item in items]
        model = BM25Okapi(tokenized, k1=k1, b=b, epsilon=epsilon) if tokenized else None
        return _CachedIndex(items=items, model=model)

    async def _load_index(self, db: AsyncSession, user_id: UUID) -> _CachedIndex:
        with self._lock:
            cached = self._cache.get(user_id)
            if cached is not None:
                self._cache.move_to_end(user_id)
                return cached
            version = self._versions.get(user_id, 0)

        rows = list(
            (
                await db.execute(
                    select(DocumentChunk, Document.filename)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(
                        Document.user_id == user_id,
                        Document.processing_status == DocumentStatus.COMPLETED,
                        Document.indexed_chunk_count > 0,
                        Document.indexed_at.is_not(None),
                    )
                    .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
                )
            ).all()
        )
        built = await run_in_threadpool(
            self._build_index, rows, self.k1, self.b, self.epsilon
        )
        with self._lock:
            if self._versions.get(user_id, 0) != version:
                return built
            self._cache[user_id] = built
            self._cache.move_to_end(user_id)
            while len(self._cache) > self.max_cached_users:
                self._cache.popitem(last=False)
            self.build_count += 1
        return built

    async def search_keyword(
        self,
        query: str,
        user_id: UUID,
        document_ids: Sequence[UUID] | None = None,
        top_k: int = 5,
        *,
        db: AsyncSession,
    ) -> list[VectorSearchResult]:
        query_tokens = tokenize_financial_text(query)
        if not query_tokens or top_k < 1:
            return []
        index = await self._load_index(db, user_id)
        if index.model is None:
            return []
        scores = await run_in_threadpool(index.model.get_scores, query_tokens)
        selected_documents = set(document_ids or [])
        query_token_set = set(query_tokens)
        critical_tokens = _critical_query_tokens(query_tokens)
        ranked: list[tuple[float, int, int, float, float, _CorpusItem]] = []
        for score, item in zip(scores, index.items, strict=True):
            if item.result.user_id != user_id:
                continue
            if selected_documents and item.result.document_id not in selected_documents:
                continue
            if not query_token_set.intersection(item.tokens):
                continue
            item_tokens = set(item.tokens)
            critical_matches = len(critical_tokens & item_tokens)
            critical_coverage = (
                critical_matches / len(critical_tokens) if critical_tokens else 0.0
            )
            critical_span = _critical_token_span(item.tokens, critical_tokens)
            query_coverage = len(query_token_set & item_tokens) / len(query_token_set)
            ranked.append(
                (
                    critical_coverage,
                    critical_span if critical_span is not None else 1_000_000,
                    critical_matches,
                    float(score),
                    query_coverage,
                    item,
                )
            )
        ranked.sort(
            key=lambda value: (
                -value[0],
                value[1],
                -value[2],
                -value[3],
                -value[4],
                str(value[5].result.chunk_id),
            )
        )
        return [
            VectorSearchResult(
                chunk_id=item.result.chunk_id,
                user_id=item.result.user_id,
                document_id=item.result.document_id,
                filename=item.result.filename,
                page_numbers=item.result.page_numbers,
                chunk_text=item.result.chunk_text,
                similarity_score=score,
                section=item.result.section,
            )
            for _, _, _, score, _, item in ranked[:top_k]
        ]
