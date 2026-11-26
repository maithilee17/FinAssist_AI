"""Validate the configured embedding runtime with a small real CPU inference."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import traceback
from pathlib import Path

from app.config import get_settings
from app.services.embedding_service import EmbeddingService, EmbeddingServiceError


def _version(module_name: str) -> str:
    module = __import__(module_name)
    return str(getattr(module, "__version__", "unknown"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load the configured BGE model and validate document/query vectors."
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Fail instead of downloading any missing model artifact.",
    )
    args = parser.parse_args()
    settings = get_settings()
    hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache_parent = hf_home if hf_home.exists() else hf_home.parent
    service = EmbeddingService(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=min(settings.embedding_batch_size, 2),
        query_prefix=settings.embedding_query_prefix,
        expected_dimension=settings.embedding_expected_dimension,
        model_revision=settings.embedding_model_revision,
        local_files_only=args.local_files_only or settings.embedding_local_files_only,
    )
    runtime = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": _version("torch"),
        "sentence_transformers": _version("sentence_transformers"),
        "model": settings.embedding_model,
        "device": settings.embedding_device or "auto",
        "expected_dimension": settings.embedding_expected_dimension,
        "batch_size": service.batch_size,
        "local_files_only": service.local_files_only,
        "cache_exists": hf_home.exists(),
        "cache_writable": os.access(cache_parent, os.W_OK),
    }
    try:
        result = service.diagnostic_check()
    except EmbeddingServiceError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "diagnostic_code": exc.code,
                    "detail": str(exc),
                    "runtime": runtime,
                },
                indent=2,
            )
        )
        traceback.print_exception(exc, file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "runtime": runtime, "result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
