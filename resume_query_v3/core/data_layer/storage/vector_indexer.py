from __future__ import annotations

import re
from typing import Any, Dict, List

from langchain_openai import OpenAIEmbeddings
from llama_index.embeddings.ollama import OllamaEmbedding


def build_vector_payload(*, chunk_payloads: List[Dict[str, Any]], config: Dict[str, Any], resume_identity: str = "") -> List[Dict[str, Any]]:
    embedder = _build_embedder(config)
    texts = [str(item.get("chunk_text", "")).strip() for item in chunk_payloads]
    vectors_by_index: Dict[int, List[float]] = {}
    if embedder is not None:
        try:
            if hasattr(embedder, "embed_documents"):
                embeddings = list(embedder.embed_documents([text for text in texts]))
                for index, embedding in enumerate(embeddings):
                    vectors_by_index[index] = list(embedding or [])
        except Exception:
            vectors_by_index = {}
    enriched: List[Dict[str, Any]] = []
    seen_project_ids: Dict[str, int] = {}
    for index, item in enumerate(chunk_payloads):
        text = str(item.get("chunk_text", "")).strip()
        base_project_id = str(item.get("project_id", "")).strip() or str(item.get("chunk_id", "")).strip() or f"project_{index + 1}"
        project_id = _unique_project_id(base_project_id, seen_project_ids, f"project_{index + 1}")
        identity = str(resume_identity or item.get("resume_identity", "")).strip()
        vector: List[float] = list(vectors_by_index.get(index, []) or [])
        if text and embedder is not None and not vector:
            try:
                if hasattr(embedder, "embed_query"):
                    vector = list(embedder.embed_query(text))
                else:
                    vector = list(embedder.get_text_embedding(text))
            except Exception:
                vector = []
        enriched.append(
            {
                **item,
                "resume_identity": identity,
                "project_id": project_id,
                "vector_id": f"{identity}:{project_id}" if identity else project_id,
                "embedding_model": _embedding_model_name(config),
                "schema_version": "v3_project_chunk_1",
                "embedding": vector,
            }
        )
    return enriched


def _unique_project_id(base: str, seen: Dict[str, int], fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(base or "").strip()).strip("_")
    cleaned = cleaned[:120] or fallback
    count = seen.get(cleaned, 0)
    seen[cleaned] = count + 1
    if count <= 0:
        return cleaned
    return f"{cleaned}_{count + 1}"


def _build_embedder(config: Dict[str, Any]) -> Any:
    provider = str(config["model"].get("embedding_provider", "openai")).strip().lower()
    if provider == "openai" and str(config["env"].get("openai_api_key", "")).strip():
        return OpenAIEmbeddings(
            model=str(config["model"].get("openai_embedding_model", "text-embedding-3-small")).strip(),
            api_key=str(config["env"].get("openai_api_key", "")).strip(),
            base_url=str(config["env"].get("openai_base_url", "https://api.openai.com/v1")).strip(),
        )
    if provider == "ollama":
        return OllamaEmbedding(
            model_name=str(config["model"].get("ollama_embedding_model", "bge-m3")).strip(),
            base_url=str(config["env"].get("ollama_host", "http://localhost:11434")).strip(),
            client_kwargs={"trust_env": False, "timeout": float(config["env"].get("ollama_timeout", 120.0))},
        )
    return None


def _embedding_model_name(config: Dict[str, Any]) -> str:
    provider = str(config["model"].get("embedding_provider", "openai")).strip().lower()
    if provider == "openai":
        return str(config["model"].get("openai_embedding_model", "text-embedding-3-small")).strip()
    return str(config["model"].get("ollama_embedding_model", "bge-m3")).strip()
