"""Shared read-only data store configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from .embedding_config import get_resume_embedding_config
from .env import load_repo_env, repo_root


def get_resume_data_config() -> Dict[str, Any]:
    """Return the SQLite/Chroma locations used by read-only tools."""
    load_repo_env()
    root = repo_root()
    v3_root = root / "resume_query_v3"
    data_root_raw = os.getenv("RESUME_DATA_ROOT", "").strip()
    data_root = Path(data_root_raw).expanduser().resolve() if data_root_raw else None
    data_dir = data_root / "resume_query_v3" / "data" if data_root else v3_root / "data"
    embedding = get_resume_embedding_config()
    chroma_collection = os.getenv("RESUME_TOOLS_CHROMA_COLLECTION", "").strip() or str(embedding["chroma_collection"])
    return {
        "paths": {
            "repo_root": root,
            "v3_root": v3_root,
            "structured_store_file": Path(os.getenv("RESUME_TOOLS_SQLITE", data_dir / "structured" / "structured_store.db")),
            "chroma_dir": Path(os.getenv("RESUME_TOOLS_CHROMA_DIR", data_dir / "vector" / "chroma_store")),
        },
        "storage": {
            "chroma_collection": chroma_collection,
        },
        "embedding": {
            "provider": embedding["provider"],
            "model": embedding["model"],
            "dimension": embedding["dimension"],
            "openai_api_key": embedding["openai_api_key"],
            "openai_base_url": embedding["openai_base_url"],
            "openai_timeout": embedding["openai_timeout"],
            "ollama_host": embedding["ollama_host"],
            "ollama_timeout": embedding["ollama_timeout"],
        },
    }
