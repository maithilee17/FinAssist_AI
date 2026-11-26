"""Northstar figures supplied in the bug report, not a dump of the live DB.

Exercise real PDF extraction, cleaning, chunking, hybrid retrieval, evidence and
claim verification with isolated storage. Live Ollama/GUI acceptance is separate.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pymupdf
import pytest

from app.models import Document, DocumentChunk, DocumentStatus, User
from app.services.adaptive_retrieval import AdaptiveRetrievalService
from app.services.claim_verifier import ClaimOverallStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import calculate
from app.services.keyword_retrieval import KeywordRetrievalService
from app.services.pdf_processor import extract_pdf_pages
from app.services.rag_pipeline import ABSTENTION_ANSWER, RagPipeline
from app.services.retrieval_service import SemanticRetrievalService
from app.services.text_chunker import chunk_pages
from app.services.vector_store import VectorChunk, VectorSearchResult

QUESTION = "Calculate its gross profit margin."


def passages(text):
    return [
        VectorSearchResult(
            chunk_id=uuid4(),
            user_id=uuid4(),
            document_id=uuid4(),
            filename="FinAssist_Sample_Financial_Report.pdf",
            page_numbers=[1],
            chunk_text=text,
            similarity_score=0.8,
        )
    ]


@pytest.mark.parametrize(
    "rows",
    [
        "Revenue: $850,000\nCost of goods sold (COGS): $510,000",
        "Revenue | $850,000\nCost of goods sold | $510,000",
        "| Revenue | $850,000 |\n| Cost of goods sold (COGS) | $510,000 |",
        "Revenue\n$850,000\nCost of goods sold (COGS)\n$510,000",
        "Revenue\n\n$850,000\n\nCost of goods sold\n\n$510,000",
        "Revenue\n$\n850,000\nCost of goods\nsold (COGS)\n$\n510,000",
        "Revenue\t\tUSD 850,000.00\nCOGS\t\tUSD 510,000.00",
        "Revenue: $850,\n000\nCOGS: $510,\n000",
        "Revenue\u00a0|\u202f$\u00a0850,000\r\nCOGS | $ 510,000",
        "Reve\u200bnue: $850,000\nCost of goods so\u00adld: $510,000",
        "Revenue: USD 0.85 million\nCOGS: $510 thousand",
        "Revenue: USD 0.85\nmillion\nCOGS: $510\nthousand",
    ],
)
def test_pdf_row_layouts_keep_exact_input_provenance(rows):
    evidence = passages("Northstar Components FY2025\n" + rows)
    proof = calculate(QUESTION, evidence)
    assert proof and "40.00%" in proof.answer
    assert "(850000" in proof.answer
    assert {fact.label for fact in proof.inputs} == {"revenue", "COGS"}
    assert {fact.amount for fact in proof.inputs} == {Decimal(850000), Decimal(510000)}
    for fact in proof.inputs:
        source = evidence[fact.source_number - 1]
        assert fact.excerpt == source.chunk_text[fact.start : fact.end]
        assert fact.chunk_id == source.chunk_id
        assert fact.document_id == source.document_id
        assert fact.user_id == source.user_id
        assert fact.filename == source.filename
        assert fact.page_numbers == tuple(source.page_numbers)
    verification = EvidenceVerifier().verify(
        QUESTION,
        evidence,
        user_id=evidence[0].user_id,
        allowed_document_ids={evidence[0].document_id},
    )
    assert verification.evidence_status == EvidenceStatus.SUFFICIENT
    checked = ClaimVerifier().verify(proof.answer, evidence)
    assert checked.overall_status == ClaimOverallStatus.VERIFIED
    assert checked.claims[0].source_chunk_ids == [evidence[0].chunk_id]


@pytest.mark.parametrize("unit", ["€", "£", "₹", "EUR", "GBP", "INR"])
def test_explicit_currency_symbols_and_codes(unit):
    assert (
        "40.00%"
        in calculate(
            QUESTION, passages(f"Revenue | {unit} 850,000\nCOGS | {unit} 510,000")
        ).answer
    )


@pytest.mark.parametrize(
    "rows",
    [
        "Revenue | $850,000",  # missing input
        "Revenue\nCOGS\n$510,000",  # never borrow another row's value
        "Revenue | 850,000\nCOGS | 510,000",  # no explicit units
        "Revenue | $850,000\nCOGS | EUR 510,000",  # incompatible units
        "Revenue | $850,000 | $700,000\nCOGS | $510,000",  # horizontal columns
        "Revenue | | $850,000\nCOGS | $510,000",  # unidentified empty column
        "Revenue\n$850,000\n$700,000\nCOGS\n$510,000",  # vertical columns
        "Revenue | $850,000\nRevenue | $700,000\nCOGS | $510,000",
        "Revenue | $850,000\nRevenue | $700,000 | $800,000\nCOGS | $510,000",
        "Revenue: $850,000\nCOGS: $510,000\nGross profit: $350,000",
        "Revenue: $850,000\nCOGS: $510,000\nGross profit: $340,000\nGross profit: $350,000",
        "Revenue: $850,000\nGross profit: $340,000\nCOGS: $510,000 $490,000",
        "FY2024 FY2025\nRevenue | $850,000\nCOGS | $510,000",
        "Revenue | $85,00,0\nCOGS | $510,000",  # malformed comma grouping
        "Revenue | $850,000\nCOGS | $510,000 60%",  # extra unidentified column
        "Revenue | $850,000\n60%\nCOGS | $510,000",  # vertical ratio column
        "Revenue\nSee note 4\n$850,000\nCOGS\n$510,000",
        "Revenue | $0\nCOGS | $510,000",
        "Revenue: $850,000\nCOGS: $-510,000",  # unsupported signed format
    ],
)
def test_ambiguous_conflicting_missing_or_unsupported_inputs_abstain(rows):
    evidence = passages(rows)
    assert calculate(QUESTION, evidence) is None
    assert (
        EvidenceVerifier()
        .verify(
            QUESTION,
            evidence,
            user_id=evidence[0].user_id,
            allowed_document_ids={evidence[0].document_id},
        )
        .evidence_status
        != EvidenceStatus.SUFFICIENT
    )


def test_separate_input_citations_and_ownership_checks():
    evidence = passages("Revenue | $850,000")
    evidence.append(
        replace(
            evidence[0],
            chunk_id=uuid4(),
            page_numbers=[2],
            chunk_text="Cost of goods sold\n$510,000",
        )
    )
    proof = calculate(QUESTION, evidence)
    assert proof.sources == (1, 2)
    checked = ClaimVerifier().verify(proof.answer, evidence)
    assert set(checked.claims[0].source_chunk_ids) == {x.chunk_id for x in evidence}
    for change in [
        {"user_id": uuid4()},
        {"document_id": uuid4()},
        {"page_numbers": []},
        {"page_numbers": [0]},
        {"filename": ""},
    ]:
        assert (
            calculate(QUESTION, [evidence[0], replace(evidence[1], **change)]) is None
        )
    for user, docs in [
        (uuid4(), {evidence[0].document_id}),
        (evidence[0].user_id, {uuid4()}),
    ]:
        assert (
            EvidenceVerifier()
            .verify(
                QUESTION,
                evidence,
                user_id=user,
                allowed_document_ids=docs,
            )
            .evidence_status
            != EvidenceStatus.SUFFICIENT
        )


@pytest.mark.parametrize(
    "before,after",
    [
        ("40.00%", "60.00%"),
        (" - ", " + "),
        (" / ", " * "),
        ("850000 - 510000", "510000 - 850000"),
        ("[Source 2]", "[Source 1]"),
    ],
)
def test_independent_arithmetic_rejects_altered_results_and_citations(before, after):
    evidence = passages("Revenue | $850,000\nReported margin: 60.00%")
    evidence.append(
        replace(
            evidence[0],
            chunk_id=uuid4(),
            page_numbers=[2],
            chunk_text="COGS | $510,000",
        )
    )
    proof = calculate(QUESTION, evidence)
    assert proof
    checked = ClaimVerifier().verify(proof.answer.replace(before, after), evidence)
    assert checked.overall_status == ClaimOverallStatus.UNSUPPORTED
    assert checked.unsupported_claims == 1
    assert checked.claims[0].source_chunk_ids == []


class NeverCalledLLM:
    model_name = "ollama-configured-calculation-test"

    async def generate(self, *args):
        raise AssertionError(
            "Validated arithmetic and abstentions must be deterministic"
        )


def northstar_pdf_chunks(tmp_path, mode, user_id, document_id):
    pdf_path = tmp_path / "northstar.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Northstar Components FY2025")
        page.insert_text((50, 85), "Income statement")
        # Text in two cells becomes label/newline/value in PyMuPDF blocks.
        rows = [("Revenue", "$850,000")]
        if mode != "missing":
            rows.append(("Cost of goods sold (COGS)", "$510,000"))
        if mode == "ambiguous":
            rows.append(("Revenue", "$700,000"))
        for y, (label, amount) in enumerate(rows, 1):
            page.insert_text((50, 110 + y * 30), label)
            page.insert_text((350, 110 + y * 30), amount)
        pdf.new_page().insert_text(
            (50, 50), "Northstar Components FY2025\nRisk: supplier concentration"
        )
        pdf.new_page().insert_text(
            (50, 50), "Northstar Components FY2025\nCash flow from operations: $118,000"
        )
        pdf.save(pdf_path)

    pages = extract_pdf_pages(pdf_path, document_id, pdf_path.name).pages
    assert "Revenue\n$850,000" in pages[0].extracted_text
    chunks = chunk_pages(
        pages, document_id=document_id, user_id=user_id, target_size=70, overlap_size=0
    )
    return pdf_path, chunks


@pytest.mark.parametrize("mode", ["complete", "missing", "ambiguous"])
def test_northstar_real_pdf_extraction_and_calculation(tmp_path, mode):
    user_id, document_id = uuid4(), uuid4()
    pdf_path, chunks = northstar_pdf_chunks(tmp_path, mode, user_id, document_id)
    evidence = [
        VectorSearchResult(
            chunk_id=c.id,
            user_id=c.user_id,
            document_id=c.document_id,
            filename=pdf_path.name,
            page_numbers=c.page_numbers,
            chunk_text=c.text,
            similarity_score=0.8,
        )
        for c in chunks
    ]
    proof = calculate(QUESTION, evidence)
    if mode == "complete":
        assert proof and "40.00%" in proof.answer
        assert (
            ClaimVerifier().verify(proof.answer, evidence).overall_status
            == ClaimOverallStatus.VERIFIED
        )
        assert {x.label for x in proof.inputs} == {"revenue", "COGS"}
        assert all(1 in x.page_numbers for x in proof.inputs)
    else:
        assert proof is None


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["complete", "missing", "ambiguous"])
async def test_northstar_pdf_through_ingestion_hybrid_pipeline(
    tmp_path,
    session_factory,
    fake_embedding_service,
    fake_vector_store,
    mode,
):
    user_id, document_id = uuid4(), uuid4()
    pdf_path, chunks = northstar_pdf_chunks(tmp_path, mode, user_id, document_id)
    vectors = [
        VectorChunk(
            id=c.id,
            user_id=c.user_id,
            document_id=c.document_id,
            filename=pdf_path.name,
            text=c.text,
            page_numbers=c.page_numbers,
            chunk_index=c.chunk_index,
        )
        for c in chunks
    ]
    fake_vector_store.add_chunks(
        vectors, fake_embedding_service.embed_documents([c.text for c in chunks])
    )
    async with session_factory() as db:
        db.add(
            User(
                id=user_id,
                full_name="Northstar regression",
                email=f"{user_id}@example.com",
                hashed_password="unused-test-hash",
            )
        )
        await db.flush()
        db.add(
            Document(
                id=document_id,
                user_id=user_id,
                filename=pdf_path.name,
                storage_path=str(pdf_path),
                file_size=pdf_path.stat().st_size,
                mime_type="application/pdf",
                page_count=3,
                processing_status=DocumentStatus.COMPLETED,
                indexed_chunk_count=len(chunks),
                indexed_at=datetime.now(UTC),
            )
        )
        await db.flush()
        db.add_all(
            [
                DocumentChunk(
                    id=c.id,
                    user_id=user_id,
                    document_id=document_id,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    token_count=c.token_count,
                    page_numbers=c.page_numbers,
                )
                for c in chunks
            ]
        )
        await db.commit()
        retrieval = AdaptiveRetrievalService(
            KeywordRetrievalService(),
            SemanticRetrievalService(fake_embedding_service, fake_vector_store),
        )
        result = await RagPipeline(
            retrieval, NeverCalledLLM(), source_excerpt_chars=5
        ).answer(
            db,
            user_id=user_id,
            question=QUESTION,
            document_ids=[document_id],
        )
    assert result.retrieval.selected_strategy.value == "hybrid"
    if mode == "complete":
        assert "(850000 - 510000) / 850000 * 100 = 40.00%" in result.answer
        assert result.verification.overall_status == "verified"
        assert result.verification.claims_checked == 1
        assert result.verification.supported_claims == 1
        assert result.verification.supporting_citations >= 1
        source = next(s for s in result.sources if "$850,000" in s.excerpt)
        assert "$510,000" in source.excerpt
        assert source.document_id == document_id
        assert 1 in source.page_numbers
        assert source.chunk_id == chunks[0].id
        assert result.model_name == "verified-decimal-calculator"
    else:
        assert result.answer == ABSTENTION_ANSWER
        assert result.sources == []
        assert result.verification.claims_checked == 0
