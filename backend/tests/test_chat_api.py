"""Authenticated PDF-to-grounded-answer workflow and chat ownership tests."""

from uuid import uuid4

import httpx
import pytest

from app.main import app
from app.services.adaptive_retrieval import AdaptiveRetrievalService
from app.services.keyword_retrieval import KeywordRetrievalService
from app.services.llm_service import (
    LLMResult,
    LLMServiceError,
    LLMTimeoutError,
    OllamaLLMService,
    OllamaModelNotFoundError,
)
from app.services.rag_dependencies import get_rag_pipeline
from app.services.rag_pipeline import RagPipeline
from app.services.retrieval_service import SemanticRetrievalService

pytestmark = pytest.mark.anyio


class GroundedFakeLLM:
    model_name = "grounded-api-test"

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResult:
        assert "using only the supplied financial document evidence" in system_prompt
        assert "FY2025 Revenue" in user_prompt
        return LLMResult(
            answer="FY2025 revenue was $1,250.50 [Source 1].",
            model_name=self.model_name,
            input_tokens=80,
            output_tokens=15,
            total_tokens=95,
        )


async def create_user_token(client: httpx.AsyncClient, email: str) -> str:
    password = "SecureChatUser123!"
    registration = await client.post(
        "/api/auth/register",
        json={"full_name": "Chat Tester", "email": email, "password": password},
    )
    assert registration.status_code == 201
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


@pytest.mark.parametrize(
    "failure,status_code",
    [
        (LLMTimeoutError("The Ollama request timed out"), 504),
        (OllamaModelNotFoundError("Model missing; run ollama pull test"), 503),
        (LLMServiceError("Ollama is not reachable"), 503),
    ],
)
async def test_ollama_failures_do_not_create_chat_history(client, failure, status_code):
    class FailingPipeline:
        async def answer(self, *args, **kwargs):
            raise failure

    app.dependency_overrides[get_rag_pipeline] = lambda: FailingPipeline()
    token = await create_user_token(client, "failure@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/chat/ask", headers=headers, json={"question": "What was revenue?"}
    )
    assert response.status_code == status_code
    assert response.json()["detail"] == str(failure)
    sessions = await client.get("/api/chat/sessions", headers=headers)
    assert sessions.json()["total"] == 0


async def test_complete_upload_to_answer_history_and_deletion_workflow(
    client: httpx.AsyncClient,
    pdf_bytes_factory,
    fake_embedding_service,
    fake_vector_store,
) -> None:
    retrieval = SemanticRetrievalService(
        fake_embedding_service,
        fake_vector_store,
        default_top_k=5,
        minimum_similarity=-1,
    )
    adaptive = AdaptiveRetrievalService(
        KeywordRetrievalService(), retrieval, default_top_k=5
    )

    def handler(request):
        import json

        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        assert "FY2025 Revenue" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "message": {"content": "FY2025 revenue was $1,250.50 [Source 1]."},
                "prompt_eval_count": 80,
                "eval_count": 15,
            },
        )

    local_llm = OllamaLLMService(
        model_name="grounded-api-test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(handler),
    )
    pipeline = RagPipeline(adaptive, local_llm)
    app.dependency_overrides[get_rag_pipeline] = lambda: pipeline

    owner_token = await create_user_token(client, "chat-owner@example.com")
    other_token = await create_user_token(client, "chat-other@example.com")
    pdf = pdf_bytes_factory(
        ["FY2025 Revenue was $1,250.50.", "Operating profit was $210.00."]
    )
    upload = await client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {owner_token}"},
        files={"file": ("financial-results.pdf", pdf, "application/pdf")},
    )
    assert upload.status_code == 201
    assert upload.json()["processing_status"] == "completed"
    assert upload.json()["indexed_chunk_count"] >= 1
    document_id = upload.json()["id"]

    answer = await client.post(
        "/api/chat/ask",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"question": "What was FY2025 revenue?", "document_ids": [document_id]},
    )
    assert answer.status_code == 200
    body = answer.json()
    assert "$1,250.50" in body["answer"]
    assert body["sources"][0]["document_id"] == document_id
    assert body["sources"][0]["filename"] == "financial-results.pdf"
    # Citations are narrowed to the page that contains the requested value rather
    # than every page spanned by the underlying multi-page chunk.
    assert body["sources"][0]["page_numbers"] == [1]
    assert "FY2025 Revenue" in body["sources"][0]["excerpt"]
    assert body["retrieval"]["selected_strategy"] == "keyword"
    assert body["retrieval"]["keyword_result_count"] >= 1
    assert body["verification"]["evidence_status"] == "sufficient"
    assert body["verification"]["overall_status"] == "verified"
    assert body["verification"]["supported_claims"] == 1
    assert body["confidence"]["calibrated_probability"] is False
    session_id = body["session_id"]

    sessions = await client.get(
        "/api/chat/sessions", headers={"Authorization": f"Bearer {owner_token}"}
    )
    history = await client.get(
        f"/api/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert sessions.json()["total"] == 1
    assert history.status_code == 200
    assert [message["role"] for message in history.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert history.json()["messages"][1]["sources"][0]["document_id"] == document_id
    assert history.json()["messages"][1]["retrieval"]["selected_strategy"] == "keyword"
    assert history.json()["messages"][1]["verification"]["overall_status"] == "verified"
    assert history.json()["messages"][1]["confidence"]["level"] in {
        "high",
        "medium",
        "low",
    }

    cross_document = await client.post(
        "/api/chat/ask",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"question": "Reveal revenue", "document_ids": [document_id]},
    )
    cross_history = await client.get(
        f"/api/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    cross_delete = await client.delete(
        f"/api/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert cross_document.status_code == 404
    assert cross_history.status_code == 404
    assert cross_delete.status_code == 404

    deleted = await client.delete(
        f"/api/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deleted.status_code == 204
    assert (
        await client.get(
            f"/api/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    ).status_code == 404


async def test_chat_requires_authentication(client: httpx.AsyncClient) -> None:
    class NeverCalledPipeline:
        pass

    app.dependency_overrides[get_rag_pipeline] = lambda: NeverCalledPipeline()
    response = await client.post(
        "/api/chat/ask", json={"question": "What was revenue?", "document_ids": []}
    )
    assert response.status_code == 401


async def test_unknown_session_is_not_disclosed(client: httpx.AsyncClient) -> None:
    token = await create_user_token(client, "unknown-session@example.com")
    response = await client.get(
        f"/api/chat/sessions/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
