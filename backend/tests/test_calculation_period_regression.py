"""The explicit year in the reported live question used to fail before parsing.

These are scoped reproduction fixtures, not a claim to have captured live rows.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.diagnostics.calculation_trace import TraceRetrieval, TraceVerifier, snapshot
from app.services.claim_verifier import ClaimOverallStatus, ClaimVerifier
from app.services.evidence_verifier import EvidenceStatus, EvidenceVerifier
from app.services.financial_calculation import calculate, extract_calculation_inputs
from app.services.vector_store import VectorSearchResult

QUESTION = "Calculate gross profit margin for FY2025."


def evidence():
    title = VectorSearchResult(
        chunk_id=uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        filename="FinAssist_Sample_Financial_Report.pdf",
        page_numbers=[1],
        chunk_text="Northstar Components\nFY2025 financial report",
        similarity_score=0.9,
    )
    return [
        title,
        replace(
            title, chunk_id=uuid4(), page_numbers=[2], chunk_text="Revenue\n$850,000"
        ),
        replace(
            title,
            chunk_id=uuid4(),
            page_numbers=[2],
            chunk_text="Cost of goods sold (COGS)\n$510,000",
        ),
    ]


def test_explicit_fy2025_is_validated_instead_of_unconditionally_rejected():
    rows = evidence()
    inputs, invalid = extract_calculation_inputs(rows)
    assert set(inputs) == {"revenue", "COGS"} and not invalid
    proof = calculate(QUESTION, rows)
    assert proof and "40.00%" in proof.answer and "FY2025" in proof.answer
    assert proof.sources == (1, 2, 3)  # period context + both arithmetic inputs
    result = EvidenceVerifier().verify(
        QUESTION,
        rows,
        user_id=rows[0].user_id,
        allowed_document_ids={rows[0].document_id},
    )
    assert result.evidence_status == EvidenceStatus.SUFFICIENT
    checked = ClaimVerifier().verify(proof.answer, rows)
    assert checked.overall_status == ClaimOverallStatus.VERIFIED
    assert set(checked.claims[0].source_chunk_ids) == {row.chunk_id for row in rows}
    assert (
        ClaimVerifier()
        .verify(proof.answer.replace("FY2025", "FY2024"), rows)
        .overall_status
        == ClaimOverallStatus.UNSUPPORTED
    )


@pytest.mark.parametrize(
    "context",
    [
        "",
        "FY2024 financial report",
        "FY2024 FY2025 comparison",
        "Copyright 2025",
        "Revenue: $2025",  # not reporting-period evidence
    ],
)
def test_missing_wrong_or_ambiguous_reporting_year_remains_an_abstention(context):
    rows = evidence()
    rows[0] = replace(rows[0], chunk_text=context)
    assert calculate(QUESTION, rows) is None
    checked = EvidenceVerifier().verify(
        QUESTION,
        rows,
        user_id=rows[0].user_id,
        allowed_document_ids={rows[0].document_id},
    )
    assert checked.evidence_status != EvidenceStatus.SUFFICIENT
    assert any("period" in item for item in checked.missing_aspects)


def test_single_period_still_needs_both_inputs_and_owned_sources():
    rows = evidence()
    assert calculate(QUESTION, rows[:2]) is None
    for changes in [
        {"user_id": uuid4()},
        {"document_id": uuid4()},
        {"page_numbers": []},
    ]:
        assert calculate(QUESTION, rows[:2] + [replace(rows[2], **changes)]) is None


def test_trace_records_exact_parser_text_and_redacts_other_scope():
    rows = evidence()
    attempts = [
        {
            "returned_passages": [
                snapshot(x, rows[0].user_id, rows[0].document_id) for x in rows
            ]
        }
    ]
    verifier = TraceVerifier(
        EvidenceVerifier(), attempts, rows[0].user_id, rows[0].document_id
    )
    verifier.verify(
        QUESTION,
        rows,
        user_id=rows[0].user_id,
        allowed_document_ids={rows[0].document_id},
    )
    assert attempts[0]["parser_called"]
    assert attempts[0]["retrieval_equals_verifier"]
    assert attempts[0]["parser_passages"] == attempts[0]["returned_passages"]
    assert attempts[0]["calculation"]["sources"] == (1, 2, 3)
    alien = replace(rows[1], user_id=uuid4(), chunk_text="PRIVATE OTHER USER CONTENT")
    assert snapshot(alien, rows[0].user_id, rows[0].document_id) == {
        "redacted_out_of_scope": True,
    }


def test_trace_detects_text_change_before_parser():
    rows = evidence()
    attempts = [
        {
            "returned_passages": [
                snapshot(x, rows[0].user_id, rows[0].document_id) for x in rows
            ]
        }
    ]
    verifier = TraceVerifier(
        EvidenceVerifier(), attempts, rows[0].user_id, rows[0].document_id
    )
    rows[1] = replace(rows[1], chunk_text="Revenue\n$700,000")
    verifier.verify(
        QUESTION,
        rows,
        user_id=rows[0].user_id,
        allowed_document_ids={rows[0].document_id},
    )
    assert not attempts[0]["retrieval_equals_verifier"]


def test_trace_error_does_not_print_credentials_or_provider_exception(
    monkeypatch,
    tmp_path,
    capsys,
):
    from app.diagnostics import calculation_trace

    monkeypatch.setattr(
        "sys.argv",
        [
            "trace",
            "--user-id",
            str(uuid4()),
            "--filename",
            "sample",
            "--output",
            str(tmp_path / "trace.json"),
        ],
    )
    monkeypatch.setattr(calculation_trace.logging, "disable", lambda level: None)

    def failed(coroutine):
        coroutine.close()
        raise RuntimeError("SECRET_PROVIDER_TOKEN_AND_PASSWORD")

    monkeypatch.setattr(calculation_trace.asyncio, "run", failed)
    with pytest.raises(SystemExit) as error:
        calculation_trace.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "SECRET_PROVIDER_TOKEN_AND_PASSWORD" not in captured.out + captured.err
    assert not (tmp_path / "trace.json").exists()


@pytest.mark.anyio
async def test_trace_wraps_real_retrieval_result_without_changing_text():
    from app.services.adaptive_retrieval import (
        AdaptiveRetrievalResult,
        RetrievalDiagnostics,
        RetrievalStrategy,
    )

    rows = evidence()

    class Retrieval:
        async def retrieve(self, *args, **kwargs):
            return AdaptiveRetrievalResult(
                rows,
                RetrievalDiagnostics(
                    RetrievalStrategy.HYBRID,
                    "test",
                    {},
                    3,
                    3,
                    3,
                    3,
                    1.0,
                ),
                {},
            )

    attempts = []
    wrapped = TraceRetrieval(
        Retrieval(), attempts, rows[0].user_id, rows[0].document_id
    )
    result = await wrapped.retrieve(None, QUESTION, top_k=5)
    assert result.retrieved_chunks is rows
    assert len(attempts[0]["returned_passages"]) == 3
