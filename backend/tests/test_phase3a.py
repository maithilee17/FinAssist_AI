"""Offline Phase 3A regressions; mocked integration is never live PDF QA."""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.evaluation.phase3a_probe import CASH, PRODUCTS, TEXT
from app.services.adaptive_retrieval import (
    AdaptiveRetrievalSelector,
    AdaptiveRetrievalService,
    RetrievalStrategy,
)
from app.services.claim_verifier import ClaimOverallStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import (
    calculate,
    cash_flow_summary,
)
from app.services.llm_service import LLMResult
from app.services.pdf_processor import ExtractedPage
from app.services.query_analyzer import FinancialQueryAnalyzer, QueryType
from app.services.question_requirements import QuestionRequirementAnalyzer
from app.services.rag_pipeline import ABSTENTION_ANSWER, RagPipeline
from app.services.text_chunker import chunk_pages
from app.services.vector_store import VectorSearchResult


def passage(text=TEXT):
    return VectorSearchResult(
        chunk_id=uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        filename="fixture.pdf",
        page_numbers=[2],
        chunk_text=text,
        similarity_score=0.9,
    )


@pytest.mark.parametrize(
    "question",
    [
        PRODUCTS,
        "Describe the distribution channels of Acme Corp in FY2025.",
        "What products did Meridian Holdings manufacture in FY2023?",
        "Explain Acme Corp's pricing strategy in FY2025.",
    ],
)
def test_descriptive_year_and_company_questions_use_hybrid(question):
    analysis = FinancialQueryAnalyzer().analyze(question)
    assert analysis.requires_semantic_context
    assert (
        AdaptiveRetrievalSelector().select(analysis).selected_strategy
        == RetrievalStrategy.HYBRID
    )


@pytest.mark.parametrize(
    "question",
    [
        "What was Northstar Components' revenue in FY2024?",
        "What were Acme Corp's total assets in FY2025?",
        "What was the net change in cash for FY2025?",
    ],
)
def test_exact_value_year_questions_preserve_keyword(question):
    analysis = FinancialQueryAnalyzer().analyze(question)
    assert not analysis.has_numeric_reference  # a fiscal filter is not an amount
    assert (
        AdaptiveRetrievalSelector().select(analysis).selected_strategy
        == RetrievalStrategy.KEYWORD
    )


def test_products_require_description_not_a_numeric_sales_amount():
    requirements = QuestionRequirementAnalyzer().analyze(PRODUCTS)
    assert not requirements.requires_numeric_values
    assert "sales" not in requirements.metrics
    assert set(requirements.conceptual_topics) == {"products", "business model"}
    row = passage(
        "Northstar Components FY2024\nNorthstar Components manufactures industrial electrical components. Its sales model is distributor-focused."
    )
    result = EvidenceVerifier().verify(
        PRODUCTS, [row], user_id=row.user_id, allowed_document_ids={row.document_id}
    )
    assert result.evidence_status == EvidenceStatus.SUFFICIENT
    missing = replace(
        row,
        chunk_text="Northstar Components FY2024\nProducts were industrial electrical components.",
    )
    assert (
        EvidenceVerifier()
        .verify(
            PRODUCTS,
            [missing],
            user_id=row.user_id,
            allowed_document_ids={row.document_id},
        )
        .evidence_status
        != EvidenceStatus.SUFFICIENT
    )


def test_cash_summary_does_not_become_a_single_metric_calculation():
    row = passage()
    assert FinancialQueryAnalyzer().analyze(CASH).query_type == QueryType.DESCRIPTIVE
    assert calculate(CASH, [row]) is None
    summary = cash_flow_summary(CASH, [row])
    assert summary and "$135,000" in summary.answer and "($90,000)" in summary.answer
    assert "($25,000)" in summary.answer and "$20,000.00" in summary.answer
    assert "net inflow" in summary.answer and "net outflow" in summary.answer
    assert "FY2025" in summary.answer and "Riverton Industries" in summary.answer
    inputs = {fact.label: fact for fact in summary.inputs}
    assert inputs["investing cash flow"].amount == Decimal(-90000)
    assert all(
        fact.excerpt == row.chunk_text[fact.start : fact.end] for fact in summary.inputs
    )
    assert (
        ClaimVerifier().verify(summary.answer, [row], question=CASH).overall_status
        == ClaimOverallStatus.VERIFIED
    )
    assert (
        EvidenceVerifier()
        .verify(
            CASH, [row], user_id=row.user_id, allowed_document_ids={row.document_id}
        )
        .evidence_status
        == EvidenceStatus.SUFFICIENT
    )
    single = calculate("Calculate net change in cash for FY2025.", [row])
    assert single and "80000 - 60000 = 20000.00 USD" in single.answer


@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace("Net cash used in financing activities\n($25,000)\n", ""),
        TEXT.replace("FY2025", "FY2024"),
        TEXT + "\nFY2024 comparative statement",
        TEXT.replace("$80,000", "$85,000"),
        TEXT.replace("($25,000)", "EUR 25,000"),
        TEXT + "\nOperating cash flow: $140,000",
        TEXT.replace("($90,000)", "($-90,000)"),
    ],
)
def test_missing_conflicting_units_years_and_signs_abstain(text):
    row = passage(text)
    assert cash_flow_summary(CASH, [row]) is None
    assert (
        EvidenceVerifier()
        .verify(
            CASH, [row], user_id=row.user_id, allowed_document_ids={row.document_id}
        )
        .evidence_status
        != EvidenceStatus.SUFFICIENT
    )


def test_summary_citations_preserve_original_source_numbers_across_documents():
    target = passage()
    other = replace(
        target,
        chunk_id=uuid4(),
        document_id=uuid4(),
        chunk_text=TEXT.replace("Riverton Industries", "Other Manufacturing"),
    )
    title = replace(
        target,
        chunk_id=uuid4(),
        page_numbers=[1],
        chunk_text="Riverton Industries FY2025",
    )
    values = replace(target, chunk_id=uuid4(), chunk_text=TEXT.split("\n", 1)[1])
    rows = [other, title, values]
    summary = cash_flow_summary(CASH, rows)
    assert summary and summary.sources == (2, 3)
    assert "[Source 1]" not in summary.answer
    checked = ClaimVerifier().verify(summary.answer, rows, question=CASH)
    assert set(checked.claims[0].source_chunk_ids) == {title.chunk_id, values.chunk_id}
    assert (
        cash_flow_summary(CASH, [title, replace(values, document_id=uuid4())]) is None
    )
    assert cash_flow_summary(CASH, [target, replace(other, user_id=uuid4())]) is None
    assert (
        cash_flow_summary(CASH, [target, replace(target, document_id=uuid4())]) is None
    )
    assert (
        cash_flow_summary(
            CASH.replace("Riverton Industries", "Unknown Manufacturing"), [target]
        )
        is None
    )


def test_summary_preserves_original_scale():
    text = TEXT.replace("$135,000", "USD 135 thousand").replace(
        "($90,000)", "(USD 90 thousand)"
    )
    text = text.replace("($25,000)", "(USD 25 thousand)").replace(
        "$60,000", "USD 60 thousand"
    )
    text = text.replace("$80,000", "USD 80 thousand").replace(
        "$20,000", "USD 20 thousand"
    )
    summary = cash_flow_summary(CASH, [passage(text)])
    assert (
        summary
        and "USD 135 thousand" in summary.answer
        and "USD 20.00 thousand" in summary.answer
    )


@pytest.mark.parametrize(
    "before,after",
    [
        ("20,000.00", "25,000.00"),
        ("($90,000)", "$90,000"),
        ("[Source 1]", "[Source 9]"),
        ("FY2025", "FY2024"),
    ],
)
def test_summary_independent_verification_rejects_tampering(before, after):
    row = passage()
    summary = cash_flow_summary(CASH, [row])
    checked = ClaimVerifier().verify(
        summary.answer.replace(before, after), [row], question=CASH
    )
    assert checked.overall_status == ClaimOverallStatus.UNSUPPORTED


@pytest.mark.parametrize(
    "extra", [" and explain why cash declined", " and report its revenue"]
)
def test_unhandled_extra_request_is_not_silently_omitted(extra):
    assert cash_flow_summary(CASH.rstrip(".") + extra, [passage()]) is None


@pytest.mark.parametrize(
    "filename,margin,chunks_count",
    [
        ("FinAssist_Sample_Financial_Report", "40.00%", 3),
        ("Northstar_Components_FY2024_Test_Report", "37.50%", 2),
        ("Riverton_Industries_FY2025_Test_Report", "35.00%", 2),
    ],
)
def test_actual_phase2_pdf_text_preserves_math_and_supporting_page_metadata(
    filename, margin, chunks_count
):
    # Exact PyMuPDF-extracted fixtures with original PDF SHA256, not invented text.
    data = json.loads(
        (Path(__file__).parent / "fixtures" / (filename + ".json")).read_text(
            encoding="utf-8"
        )
    )
    doc, user = uuid4(), uuid4()
    pages = [
        ExtractedPage(doc, data["filename"], p["page_number"], p["text"])
        for p in data["pages"]
    ]
    chunks = chunk_pages(pages, document_id=doc, user_id=user)
    assert len(chunks) == chunks_count
    rows = [
        VectorSearchResult(
            chunk_id=c.id,
            user_id=user,
            document_id=doc,
            filename=data["filename"],
            page_numbers=c.page_numbers,
            chunk_text=c.text,
            similarity_score=0.9,
        )
        for c in chunks
    ]
    year = "2024" if "FY2024" in filename else "2025"
    proof = calculate(f"Calculate gross profit margin for FY{year}.", rows)
    assert proof and margin in proof.answer
    assert (
        ClaimVerifier().verify(proof.answer, rows).overall_status
        == ClaimOverallStatus.VERIFIED
    )
    if filename.startswith("Northstar_"):
        check = EvidenceVerifier().verify(
            PRODUCTS, rows, user_id=user, allowed_document_ids={doc}
        )
        assert check.evidence_status == EvidenceStatus.SUFFICIENT
        assert any(
            3 in row.page_numbers
            and "distributor-focused sales model" in row.chunk_text
            for row in rows
        )
    if filename.startswith("Riverton"):
        summary = cash_flow_summary(CASH, rows)
        assert summary and "$20,000.00" in summary.answer
        checked = ClaimVerifier().verify(summary.answer, rows, question=CASH)
        assert checked.overall_status == ClaimOverallStatus.VERIFIED
        for source in summary.sources:
            assert rows[source - 1].document_id == doc
            assert 2 in rows[source - 1].page_numbers


class MemoryPipeline(RagPipeline):
    async def _allowed_document_ids(self, db, user_id, requested_ids):
        return list(requested_ids)


@pytest.mark.anyio
@pytest.mark.parametrize("question", [PRODUCTS, CASH])
async def test_mocked_pipeline_routes_and_returns_complete_cited_answer(question):
    # Mocked integration, not the Phase 2 PDFs or real embeddings/Ollama.
    row = (
        passage()
        if question == CASH
        else passage(
            "Northstar Components FY2024\nNorthstar Components manufactures industrial electrical components. Its sales model is distributor-focused."
        )
    )
    calls = []

    class Keyword:
        async def search_keyword(self, query, user_id, document_ids, top_k, **kwargs):
            calls.append((user_id, document_ids, top_k))
            return [row]

    class Semantic:
        def retrieve(self, query, *, user_id, document_ids, top_k):
            calls.append((user_id, document_ids, top_k))
            return [row]

    class LLM:
        model_name = "mocked-ollama"

        async def generate(self, system, prompt):
            assert question == PRODUCTS
            return LLMResult(
                answer="Northstar Components manufactures industrial electrical components [Source 1]. Its sales model is distributor-focused [Source 1].",
                model_name=self.model_name,
            )

    pipeline = MemoryPipeline(AdaptiveRetrievalService(Keyword(), Semantic()), LLM())
    result = await pipeline.answer(
        None, user_id=row.user_id, question=question, document_ids=[row.document_id]
    )
    assert result.answer != ABSTENTION_ANSWER
    assert result.retrieval.selected_strategy == RetrievalStrategy.HYBRID
    assert result.verification.overall_status == "verified"
    assert all(
        user == row.user_id and docs == [row.document_id] and depth == 5
        for user, docs, depth in calls
    )
