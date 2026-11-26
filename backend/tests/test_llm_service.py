"""Ollama provider response, usage, and failure handling."""

import json

import httpx
import pytest

from app.config import Settings
from app.services.llm_service import (
    LLMConfigurationError,
    LLMServiceError,
    LLMTimeoutError,
    OllamaLLMService,
    OllamaModelNotFoundError,
    create_llm_service,
)

pytestmark = pytest.mark.anyio


async def test_ollama_chat_api_parses_text_and_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert payload["messages"] == [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "evidence"},
        ]
        assert payload["options"]["num_predict"] == 100
        return httpx.Response(
            200,
            json={
                "model": "local-test",
                "message": {"content": "Local grounded answer."},
                "prompt_eval_count": 30,
                "eval_count": 7,
            },
        )

    service = OllamaLLMService(
        model_name="local-test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(handler),
    )
    result = await service.generate("system", "evidence")
    assert result.answer == "Local grounded answer."
    assert result.total_tokens == 37


async def test_malformed_and_timed_out_provider_responses_are_clear_errors() -> None:
    malformed = OllamaLLMService(
        model_name="test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": {"content": None}})
        ),
    )

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    timed_out = OllamaLLMService(
        model_name="local-test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(LLMServiceError, match="malformed"):
        await malformed.generate("system", "evidence")
    with pytest.raises(LLMTimeoutError, match="timed out"):
        await timed_out.generate("system", "evidence")


def test_ollama_provider_selection_does_not_require_cloud_key() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        ollama_base_url="http://host.docker.internal:11434",
        ollama_model="llama3.2:1b",
    )

    service = create_llm_service(settings)

    assert isinstance(service, OllamaLLMService)
    assert service.base_url == "http://host.docker.internal:11434"
    assert service.model_name == "llama3.2:1b"


def test_ollama_defaults_match_native_setup() -> None:
    settings = Settings(_env_file=None, llm_provider="ollama")

    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen2.5:7b"
    assert settings.ollama_connect_timeout_seconds == 5.0


async def test_ollama_connection_and_missing_model_errors_are_actionable() -> None:
    def connection_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    unavailable = OllamaLLMService(
        model_name="llama3.2:1b",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(connection_failure),
    )
    missing_model = OllamaLLMService(
        model_name="missing-local-model",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                404, json={"error": "model 'missing-local-model' not found"}
            )
        ),
    )

    with pytest.raises(LLMServiceError, match="host.docker.internal"):
        await unavailable.generate("system", "evidence")
    with pytest.raises(OllamaModelNotFoundError, match="ollama pull"):
        await missing_model.generate("system", "evidence")


@pytest.mark.parametrize(
    ("response", "expected_message"),
    [
        (httpx.Response(200, json={"message": {}}), "malformed"),
        (httpx.Response(500, json={"error": "internal failure"}), "HTTP 500"),
    ],
)
async def test_ollama_malformed_and_server_errors_are_safe(
    response: httpx.Response, expected_message: str
) -> None:
    service = OllamaLLMService(
        model_name="llama3.2:1b",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(lambda request: response),
    )

    with pytest.raises(LLMServiceError, match=expected_message):
        await service.generate("system", "evidence")


@pytest.mark.parametrize("provider", ["gemini", "openai", "unknown"])
def test_cloud_or_unknown_provider_rejected(provider):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider=provider)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"message": {"content": 42}},
        {"message": {"content": ""}},
        {"message": {"content": "x"}, "eval_count": -1},
        {"message": {"content": "partial"}, "done": False},
    ],
)
async def test_invalid_envelopes_rejected(payload):
    service = OllamaLLMService(
        model_name="test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        ),
    )
    with pytest.raises(LLMServiceError, match="malformed"):
        await service.generate("system", "evidence")


@pytest.mark.parametrize(
    "models,missing", [([{"name": "test:latest"}], False), ([], True)]
)
async def test_model_readiness(models, missing):
    service = OllamaLLMService(
        model_name="test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": models})
        ),
    )
    if missing:
        with pytest.raises(OllamaModelNotFoundError):
            await service.check_health()
    else:
        await service.check_health()


def test_factory_fails_closed_even_for_mutated_settings():
    settings = Settings(_env_file=None, llm_provider="ollama")
    object.__setattr__(settings, "llm_provider", "unsupported")
    with pytest.raises(LLMConfigurationError):
        create_llm_service(settings)


@pytest.mark.parametrize("models", [[None], [{"name": []}], ["test"], {}])
async def test_malformed_model_inventory_is_safe(models):
    service = OllamaLLMService(
        model_name="test",
        base_url="http://ollama.test",
        timeout_seconds=5,
        connect_timeout_seconds=1,
        max_output_tokens=100,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": models})
        ),
    )
    with pytest.raises(LLMServiceError, match="readiness failed"):
        await service.check_health()
