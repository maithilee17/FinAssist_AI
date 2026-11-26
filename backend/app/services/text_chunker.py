"""Page-aware, paragraph-preferred text chunking for future retrieval."""

import hashlib
import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from app.services.financial_table_extractor import (
    FinancialTable,
    encode_table_chunk,
    render_table,
)
from app.services.pdf_processor import ExtractedPage

_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


@dataclass(frozen=True, slots=True)
class TextChunk:
    id: UUID
    document_id: UUID
    user_id: UUID
    chunk_index: int
    text: str
    token_count: int
    page_numbers: list[int]


@dataclass(frozen=True, slots=True)
class _TextUnit:
    text: str
    page_numbers: tuple[int, ...]
    token_count: int
    is_table: bool = False


def estimate_token_count(text: str) -> int:
    """Return a deterministic tokenizer-independent approximation."""

    return len(_TOKEN_PATTERN.findall(text))


def _split_oversized_text(
    text: str, page_number: int, target_size: int, overlap_size: int
) -> list[_TextUnit]:
    matches = list(_TOKEN_PATTERN.finditer(text))
    if not matches:
        return []
    units: list[_TextUnit] = []
    step = max(1, target_size - overlap_size)
    for start in range(0, len(matches), step):
        batch = matches[start : start + target_size]
        part = text[batch[0].start() : batch[-1].end()].strip()
        if part:
            units.append(_TextUnit(part, (page_number,), len(batch)))
    return units


def _page_units(
    pages: list[ExtractedPage], target_size: int, overlap_size: int
) -> list[_TextUnit]:
    units: list[_TextUnit] = []
    for page in pages:
        tables = [
            FinancialTable.model_validate(value)
            for value in page.metadata.get("financial_tables", [])
            if value.get("status") == "certain"
        ]
        narrative = (
            str(page.metadata.get("narrative_text", page.extracted_text))
            if tables
            else page.extracted_text
        )
        if any(
            value.get("status") == "uncertain"
            for value in page.metadata.get("financial_tables", [])
        ):
            narrative = (
                "[FINASSIST_TABLE_UNCERTAIN] Uncertain table structure; raw page text follows.\n"
                + narrative
            )
        for paragraph in _PARAGRAPH_BREAK.split(narrative):
            text = paragraph.strip()
            if not text:
                continue
            token_count = estimate_token_count(text)
            if token_count > target_size:
                units.extend(
                    _split_oversized_text(
                        text, page.page_number, target_size, overlap_size
                    )
                )
            else:
                units.append(_TextUnit(text, (page.page_number,), token_count))
        for table in tables:
            units.extend(_table_units(table, target_size))
    return units


def _table_units(table: FinancialTable, target_size: int) -> list[_TextUnit]:
    # Storage retains machine-readable provenance. BGE and Ollama receive the
    # compact financial rendering, so budget that representation rather than
    # JSON keys, UUIDs and geometry. Reserve tokenizer headroom for BGE's limit.
    table_budget = min(target_size, 350)

    def encode(rows):
        value = table.model_copy(update={"rows": rows, "header_rows": []})
        return encode_table_chunk(value)

    def cost(rows):
        return estimate_token_count(
            render_table(table.model_copy(update={"rows": rows}))
        )

    groups = []
    current = []
    for row in table.rows:
        if row.kind == "repeated_header":
            continue
        if cost(current + [row]) > table_budget and current:
            groups.append(encode(current))
            current = []
        if cost([row]) > table_budget:
            # Never sever a row from its column definitions and then present it
            # as calculable evidence. The complete table remains in page JSON.
            warning = (
                "[FINASSIST_TABLE_UNCERTAIN] table row/context exceeds chunk budget.\n"
            )
            raw = render_table(table.model_copy(update={"rows": [row]}))
            for part in _split_oversized_text(
                raw, table.page_number, max(1, target_size - 25), 0
            ):
                groups.append(warning + part.text)
            continue
        current.append(row)
    if current:
        groups.append(encode(current))
    from app.services.financial_table_extractor import table_evidence_text

    return [
        _TextUnit(
            text,
            (table.page_number,),
            estimate_token_count(table_evidence_text(text)),
            True,
        )
        for text in groups
    ]


def _overlap_tail(units: list[_TextUnit], overlap_size: int) -> list[_TextUnit]:
    if overlap_size <= 0:
        return []
    selected: list[_TextUnit] = []
    tokens = 0
    for unit in reversed(units):
        if selected and tokens + unit.token_count > overlap_size:
            break
        selected.append(unit)
        tokens += unit.token_count
        if tokens >= overlap_size:
            break
    return list(reversed(selected))


def chunk_pages(
    pages: list[ExtractedPage],
    *,
    document_id: UUID,
    user_id: UUID,
    target_size: int = 500,
    overlap_size: int = 100,
) -> list[TextChunk]:
    if target_size < 1 or overlap_size < 0 or overlap_size >= target_size:
        raise ValueError(
            "Chunk target must be positive and overlap must be smaller than target"
        )
    if any(page.document_id != document_id for page in pages):
        raise ValueError("Cannot mix pages from different documents")

    units = _page_units(pages, target_size, overlap_size)
    grouped: list[list[_TextUnit]] = []
    current: list[_TextUnit] = []
    current_tokens = 0

    for unit in units:
        if unit.is_table:
            if current:
                grouped.append(current)
                current = []
                current_tokens = 0
            grouped.append([unit])
            continue
        if current and current_tokens + unit.token_count > target_size:
            grouped.append(current)
            current = _overlap_tail(current, overlap_size)
            current_tokens = sum(item.token_count for item in current)
            while current and current_tokens + unit.token_count > target_size:
                removed = current.pop(0)
                current_tokens -= removed.token_count
        current.append(unit)
        current_tokens += unit.token_count
    if current:
        grouped.append(current)

    chunks: list[TextChunk] = []
    for index, group in enumerate(grouped):
        text = "\n\n".join(item.text for item in group).strip()
        page_numbers = list(
            dict.fromkeys(page for item in group for page in item.page_numbers)
        )
        content_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        stable_id = uuid5(
            NAMESPACE_URL,
            f"finassist:{document_id}:chunk:{index}:{','.join(map(str, page_numbers))}:{content_digest}",
        )
        chunks.append(
            TextChunk(
                id=stable_id,
                document_id=document_id,
                user_id=user_id,
                chunk_index=index,
                text=text,
                token_count=group[0].token_count
                if group[0].is_table
                else estimate_token_count(text),
                page_numbers=page_numbers,
            )
        )
    return chunks
