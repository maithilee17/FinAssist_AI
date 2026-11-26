"""Local Ollama adapter for grounded answer generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    pass


class LLMServiceError(RuntimeError):
    pass


class LLMTimeoutError(LLMServiceError):
    pass


class OllamaModelNotFoundError(LLMServiceError):
    pass


@dataclass(frozen=True, slots=True)
class LLMResult:
    answer: str
    model_name: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None


class LLMService(Protocol):
    model_name: str

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResult: ...


class OllamaLLMService:
    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        timeout_seconds: float,
        connect_timeout_seconds: float,
        max_output_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
        num_ctx: int = 8192,
    ) -> None:
        if not model_name:
            raise LLMConfigurationError("OLLAMA_MODEL must be configured")
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.transport = transport
        self.num_ctx = num_ctx

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResult:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.timeout_seconds, connect=self.connect_timeout_seconds
                ),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model_name,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "options": {
                            "num_predict": self.max_output_tokens,
                            "num_ctx": self.num_ctx,
                            "temperature": 0,
                        },
                    },
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("The Ollama request timed out") from exc
        except httpx.ConnectError as exc:
            raise LLMServiceError(
                "Ollama is not reachable. Ensure Ollama is running and the backend "
                "can access host.docker.internal:11434."
            ) from exc
        except httpx.HTTPStatusError as exc:
            error_message = ""
            try:
                error_message = str(exc.response.json().get("error") or "").lower()
            except (TypeError, ValueError, AttributeError):
                pass
            if "model" in error_message and (
                "not found" in error_message or "pull" in error_message
            ):
                raise OllamaModelNotFoundError(
                    f"Ollama model '{self.model_name}' is not installed. Run "
                    f"'ollama pull {self.model_name}' on the Windows host."
                ) from exc
            logger.warning(
                "Ollama returned an HTTP error status=%s model=%s",
                exc.response.status_code,
                self.model_name,
            )
            raise LLMServiceError(
                f"Ollama returned HTTP {exc.response.status_code}. Check the local "
                "Ollama service logs."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMServiceError("The Ollama service is unavailable") from exc

        try:
            data = response.json()
            if (
                not isinstance(data, dict)
                or data.get("error")
                or data.get("done") is False
            ):
                raise ValueError("invalid response envelope")
            content = data["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content must be text")
            answer = content.strip()
            if not answer:
                raise ValueError("empty output")
            input_tokens = data.get("prompt_eval_count")
            output_tokens = data.get("eval_count")
            for count in (input_tokens, output_tokens):
                if count is not None and (type(count) is not int or count < 0):
                    raise ValueError("invalid token count")
            total = (
                int(input_tokens) + int(output_tokens)
                if input_tokens is not None and output_tokens is not None
                else None
            )
            return LLMResult(
                answer=answer,
                model_name=str(data.get("model") or self.model_name),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total,
            )
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise LLMServiceError("Ollama returned a malformed response") from exc

    async def check_health(self) -> None:
        """Check model availability without generation or downloads."""
        try:
            async with httpx.AsyncClient(
                timeout=self.connect_timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            models = response.json()["models"]
            if not isinstance(models, list):
                raise TypeError("invalid models")
            names = set()
            for item in models:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    raise TypeError("invalid model entry")
                names.add(item["name"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LLMServiceError(
                "Ollama readiness failed. Start Ollama and verify OLLAMA_BASE_URL "
                "from the backend; Docker Desktop uses host.docker.internal:11434."
            ) from exc
        expected = (
            self.model_name if ":" in self.model_name else f"{self.model_name}:latest"
        )
        if self.model_name not in names and expected not in names:
            raise OllamaModelNotFoundError(
                f"Model '{self.model_name}' is missing. After approval, run "
                f"'ollama pull {self.model_name}' on the host."
            )


def create_llm_service(settings: Settings) -> OllamaLLMService:
    if settings.llm_provider != "ollama":
        raise LLMConfigurationError("Only LLM_PROVIDER=ollama is supported")
    return OllamaLLMService(
        model_name=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        connect_timeout_seconds=settings.ollama_connect_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        num_ctx=settings.ollama_num_ctx,
    )
