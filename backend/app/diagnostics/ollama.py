"""Check Ollama without downloads; generation requires an explicit flag."""

import argparse
import asyncio

from app.config import get_settings
from app.services.llm_service import LLMServiceError, create_llm_service


async def run(generate: bool) -> None:
    service = create_llm_service(get_settings())
    await service.check_health()
    print(f"Ollama ready; configured model: {service.model_name}")
    if generate:
        result = await service.generate(
            "Answer using only the supplied evidence.",
            "Evidence: FY2025 revenue was 100 million USD. What was revenue?",
        )
        print(f"Generation succeeded; output characters: {len(result.answer)}")
        print(
            f"Input tokens: {result.input_tokens}; output tokens: {result.output_tokens}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.generate))
    except LLMServiceError as exc:
        parser.exit(1, f"Ollama diagnostic failed: {exc}\n")


if __name__ == "__main__":
    main()
