from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import chromadb

from resume_query_common import get_resume_embedding_config
from resume_query_common.env import load_repo_env


class ResumeVectorReader:
    def __init__(self, *, persist_dir: Path, collection_name: str):
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name

    def list_project_chunks(
        self, resume_identity: str, *, source_type: str | None = None
    ) -> List[Dict[str, Any]]:
        if not self.persist_dir.exists():
            return []
        collection = self._collection()
        try:
            result = collection.get(
                where={"resume_identity": resume_identity},
                include=["documents", "metadatas"],
            )
        except Exception:
            return []
        ids = list(result.get("ids", []) or [])
        documents = list(result.get("documents", []) or [])
        metadatas = list(result.get("metadatas", []) or [])
        rows: List[Dict[str, Any]] = []
        for index, vector_id in enumerate(ids):
            metadata = dict(
                metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            )
            if (
                source_type
                and str(metadata.get("source_type", "") or "project_experience")
                != source_type
            ):
                continue
            rows.append(
                {
                    "vector_id": str(vector_id),
                    "chunk_text": str(
                        documents[index] if index < len(documents) else ""
                    ),
                    "metadata": metadata,
                }
            )
        return rows

    def search_project_chunks(
        self,
        *,
        query: str,
        top_k: int = 20,
        candidate_ids: List[str] | None = None,
        source_types: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Search project chunks by query embedding.

        This is intentionally read-only. Embedding/vector failures are returned
        as warnings so callers can fall back to structured recall.
        """
        warnings: List[str] = []
        if not self.persist_dir.exists():
            return {
                "rows": [],
                "warnings": [f"chroma path not found: {self.persist_dir}"],
            }
        query_text = str(query or "").strip()
        if not query_text:
            return {"rows": [], "warnings": ["empty vector query"]}
        embedding = _embed_query(query_text, warnings)
        if not embedding:
            return {"rows": [], "warnings": warnings or ["query embedding unavailable"]}
        try:
            collection = self._collection()
            kwargs: Dict[str, Any] = {
                "query_embeddings": [embedding],
                "n_results": max(int(top_k or 0), 1),
                "include": ["documents", "metadatas", "distances"],
            }
            where_filters: List[Dict[str, Any]] = []
            if candidate_ids:
                where_filters.append(
                    {
                        "resume_identity": {
                            "$in": [
                                str(item) for item in candidate_ids if str(item).strip()
                            ]
                        }
                    }
                )
            if source_types:
                where_filters.append(
                    {
                        "source_type": {
                            "$in": [
                                str(item) for item in source_types if str(item).strip()
                            ]
                        }
                    }
                )
            if len(where_filters) == 1:
                kwargs["where"] = where_filters[0]
            elif where_filters:
                kwargs["where"] = {"$and": where_filters}
            result = collection.query(**kwargs)
        except Exception as error:
            return {"rows": [], "warnings": [f"{type(error).__name__}: {error}"]}
        ids = list((result.get("ids") or [[]])[0] or [])
        documents = list((result.get("documents") or [[]])[0] or [])
        metadatas = list((result.get("metadatas") or [[]])[0] or [])
        distances = list((result.get("distances") or [[]])[0] or [])
        rows: List[Dict[str, Any]] = []
        for index, vector_id in enumerate(ids):
            metadata = dict(
                metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            )
            if source_types:
                row_source_type = str(
                    metadata.get("source_type", "") or "project_experience"
                )
                if row_source_type not in set(source_types):
                    continue
            rows.append(
                {
                    "vector_id": str(vector_id),
                    "chunk_text": str(
                        documents[index] if index < len(documents) else ""
                    ),
                    "metadata": metadata,
                    "distance": (
                        float(distances[index])
                        if index < len(distances) and distances[index] is not None
                        else None
                    ),
                    "rank": index + 1,
                }
            )
        return {"rows": rows, "warnings": warnings}

    def health(self) -> Dict[str, Any]:
        if not self.persist_dir.exists():
            return {
                "ok": False,
                "path": str(self.persist_dir),
                "collection": self.collection_name,
                "count": 0,
            }
        try:
            collection = self._collection()
            return {
                "ok": True,
                "path": str(self.persist_dir),
                "collection": self.collection_name,
                "count": collection.count(),
            }
        except Exception as error:
            return {
                "ok": False,
                "path": str(self.persist_dir),
                "collection": self.collection_name,
                "error": f"{type(error).__name__}: {error}",
            }

    def _collection(self) -> Any:
        client = chromadb.PersistentClient(path=str(self.persist_dir))
        return client.get_or_create_collection(self.collection_name)


def parse_metadata_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        loaded = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded if str(item).strip()]


def _embed_query(query: str, warnings: List[str]) -> List[float]:
    load_repo_env()
    config = get_resume_embedding_config()
    provider = str(config.get("provider", "ollama")).strip().lower()
    if provider == "openai":
        return _embed_query_openai(query, config, warnings)
    return _embed_query_ollama(query, config, warnings)


def _embed_query_openai(
    query: str, config: Dict[str, Any], warnings: List[str]
) -> List[float]:
    try:
        from langchain_openai import OpenAIEmbeddings

        api_key = str(config.get("openai_api_key", "")).strip()
        if not api_key:
            warnings.append("OPENAI_API_KEY is required for OpenAI query embedding")
            return []
        embedder = OpenAIEmbeddings(
            model=str(config.get("model", "text-embedding-3-small")).strip(),
            api_key=api_key,
            base_url=str(
                config.get("openai_base_url", "https://api.openai.com/v1")
            ).strip(),
        )
        return list(embedder.embed_query(query) or [])
    except Exception as error:
        warnings.append(f"{type(error).__name__}: {error}")
        return []


def _embed_query_ollama(
    query: str, config: Dict[str, Any], warnings: List[str]
) -> List[float]:
    try:
        from llama_index.embeddings.ollama import OllamaEmbedding

        embedder = OllamaEmbedding(
            model_name=str(config.get("model", "bge-m3")).strip() or "bge-m3",
            base_url=str(config.get("ollama_host", "http://localhost:11434")).strip()
            or "http://localhost:11434",
            client_kwargs={
                "trust_env": False,
                "timeout": float(config.get("ollama_timeout", 120.0) or 120),
            },
        )
        return list(embedder.get_query_embedding(query) or [])
    except Exception as error:
        warnings.append(f"{type(error).__name__}: {error}")
        return []
