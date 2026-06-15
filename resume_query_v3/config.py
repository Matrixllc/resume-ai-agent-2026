from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from resume_query_common.embedding_config import get_resume_embedding_config
from resume_query_common.env import load_repo_env, repo_root

load_repo_env()


def get_config() -> Dict[str, Any]:
    app_root = Path(__file__).resolve().parent
    root = repo_root()
    data_root_raw = os.getenv("RESUME_DATA_ROOT", "").strip()
    data_root = Path(data_root_raw).expanduser().resolve() if data_root_raw else None
    data_dir = data_root / "data" if data_root else root / "data"
    resume_dir = data_dir / "resume"
    taxonomy_dir = app_root.parent / "shared_taxonomy"
    embedding = get_resume_embedding_config()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    chat_provider = os.getenv("RESUME_V3_CHAT_PROVIDER", "").strip().lower() or ("openai" if openai_api_key else "ollama")
    return {
        "paths": {
            "repo_root": root,
            "app_root": app_root,
            "resume_dir": resume_dir,
            "configs_dir": app_root / "configs",
            "section_aliases_file": app_root / "configs" / "section_aliases.yaml",
            "routing_file": app_root / "configs" / "routing.yaml",
            "chunking_file": app_root / "configs" / "chunking.yaml",
            "validate_file": app_root / "configs" / "validate.yaml",
            "taxonomy_dir": taxonomy_dir,
            "global_concepts_file": taxonomy_dir / "concepts" / "global.yaml",
            "domains_dir": taxonomy_dir / "domains",
            "benchmark_cases_dir": app_root / "benchmarks" / "cases",
            "benchmark_expected_file": app_root / "benchmarks" / "expected_results.json",
            "benchmark_reports_dir": app_root / "benchmarks" / "reports",
            "logs_latest_dir": app_root / "logs" / "latest",
            "logs_history_dir": app_root / "logs" / "history",
            "data_dir": data_dir,
            "jobs_db": data_dir / "structured" / "pipeline_jobs.db",
            "structured_store_file": data_dir / "structured" / "structured_store.db",
            "vector_payload_file": data_dir / "vector" / "vector_payload.json",
            "chroma_dir": data_dir / "vector" / "chroma_store",
            "last_prompt_file": app_root / "logs" / "latest" / "last_llm_prompt.txt",
            "last_response_file": app_root / "logs" / "latest" / "last_llm_response.txt",
            "last_run_file": app_root / "logs" / "latest" / "last_run.json",
            "last_log_file": app_root / "logs" / "latest" / "last_run_log.txt",
        },
        "ingestion": {
            "use_docling": True,
            "domain_top_k": 4,
            "prompt_max_blocks": int(os.getenv("RESUME_V3_PROMPT_MAX_BLOCKS", "18")),
            "prompt_max_chunk_candidates": int(os.getenv("RESUME_V3_PROMPT_MAX_CHUNKS", "10")),
            "default_file": "",
        },
        "upload": {
            "resume_upload_dir": Path(os.getenv("RESUME_UPLOAD_DIR", resume_dir / "uploads")),
            "max_upload_bytes": int(os.getenv("RESUME_UPLOAD_MAX_MB", "20")) * 1024 * 1024,
            "allowed_extensions": [".pdf", ".docx", ".doc"],
        },
        "model": {
            "chat_provider": chat_provider,
            "openai_model": os.getenv("RESUME_V3_OPENAI_MODEL", "gpt-4.1-mini").strip(),
            "llm_model": os.getenv("RESUME_V3_OLLAMA_MODEL", "llama3:latest").strip(),
            "embedding_provider": embedding["provider"],
            "openai_embedding_model": os.getenv("RESUME_V3_OPENAI_EMBED_MODEL", "text-embedding-3-small").strip(),
            "ollama_embedding_model": os.getenv("RESUME_V3_EMBED_MODEL", "bge-m3").strip(),
        },
        "env": {
            "openai_api_key": openai_api_key,
            "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            "openai_timeout": float(os.getenv("OPENAI_TIMEOUT", "120")),
            "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434").strip(),
            "ollama_timeout": float(os.getenv("OLLAMA_TIMEOUT", "120")),
        },
        "performance": {
            "llm_temperature": float(os.getenv("RESUME_V3_LLM_TEMPERATURE", "0.0")),
            "llm_num_predict": int(os.getenv("RESUME_V3_LLM_NUM_PREDICT", "1200")),
        },
        "storage": {
            "structured_backend": os.getenv("RESUME_V3_STRUCTURED_BACKEND", "sqlite").strip(),
            "vector_backend": os.getenv("RESUME_V3_VECTOR_BACKEND", "chroma").strip(),
            "chroma_collection": embedding["chroma_collection"],
            "embedding_dimension": embedding["dimension"],
        },
        "logging": {
            "verbose_third_party": os.getenv("RESUME_V3_VERBOSE_THIRD_PARTY", "").strip().lower() in {"1", "true", "yes", "on"},
        },
    }
