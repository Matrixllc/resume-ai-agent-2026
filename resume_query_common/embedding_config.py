"""Shared embedding configuration for ingestion and read-only query tools."""

from __future__ import annotations

import os
import re
from typing import Any, Dict

from .env import load_repo_env


def get_resume_embedding_config() -> Dict[str, Any]:
    """Return the embedding contract shared by ingestion and query readers."""
    load_repo_env()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    provider = os.getenv("RESUME_V3_EMBED_PROVIDER", "").strip().lower() or ("openai" if openai_api_key else "ollama")
    if provider not in {"openai", "ollama"}:
        provider = "openai" if openai_api_key else "ollama"
    openai_model = os.getenv("RESUME_V3_OPENAI_EMBED_MODEL", "text-embedding-3-small").strip()
    ollama_model = os.getenv("RESUME_V3_EMBED_MODEL", "bge-m3").strip()
    model = openai_model if provider == "openai" else ollama_model
    explicit_collection = os.getenv("RESUME_V3_CHROMA_COLLECTION", "").strip()
    collection_name = explicit_collection or _default_collection_name(provider=provider, model=model)
    return {
        "provider": provider,
        "model": model,
        "dimension": _known_embedding_dimension(provider=provider, model=model),
        "chroma_collection": collection_name,
        "openai_api_key": openai_api_key,
        "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
        "openai_timeout": float(os.getenv("OPENAI_TIMEOUT", "120")),
        "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434").strip(),
        "ollama_timeout": float(os.getenv("OLLAMA_TIMEOUT", "120")),
    }


def _default_collection_name(*, provider: str, model: str) -> str:
    return f"resume_v3_project_chunks_{_slug(provider)}_{_slug(model)}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_") or "default"


def _known_embedding_dimension(*, provider: str, model: str) -> int | None:
    normalized = str(model or "").strip().lower()
    if provider == "openai":
        if normalized in {"text-embedding-3-small", "text-embedding-ada-002"}:
            return 1536
        if normalized == "text-embedding-3-large":
            return 3072
    if provider == "ollama" and normalized == "bge-m3":
        return 1024
    return None
