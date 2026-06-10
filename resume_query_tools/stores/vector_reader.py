from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import chromadb


class ResumeVectorReader:
    def __init__(self, *, persist_dir: Path, collection_name: str):
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name

    def list_project_chunks(self, resume_identity: str) -> List[Dict[str, Any]]:
        if not self.persist_dir.exists():
            return []
        collection = self._collection()
        try:
            result = collection.get(where={"resume_identity": resume_identity}, include=["documents", "metadatas"])
        except Exception:
            return []
        ids = list(result.get("ids", []) or [])
        documents = list(result.get("documents", []) or [])
        metadatas = list(result.get("metadatas", []) or [])
        rows: List[Dict[str, Any]] = []
        for index, vector_id in enumerate(ids):
            metadata = dict(metadatas[index] if index < len(metadatas) and metadatas[index] else {})
            rows.append(
                {
                    "vector_id": str(vector_id),
                    "chunk_text": str(documents[index] if index < len(documents) else ""),
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
    ) -> Dict[str, Any]:
        """Search project chunks by query embedding.

        This is intentionally read-only. Embedding/vector failures are returned
        as warnings so callers can fall back to structured recall.
        """
        warnings: List[str] = []
        if not self.persist_dir.exists():
            return {"rows": [], "warnings": [f"chroma path not found: {self.persist_dir}"]}
        query_text = str(query or "").strip()
        if not query_text:
            return {"rows": [], "warnings": ["empty vector query"]}
        embedding = _embed_query_bge_m3(query_text, warnings)
        if not embedding:
            return {"rows": [], "warnings": warnings or ["query embedding unavailable"]}
        try:
            collection = self._collection()
            kwargs: Dict[str, Any] = {
                "query_embeddings": [embedding],
                "n_results": max(int(top_k or 0), 1),
                "include": ["documents", "metadatas", "distances"],
            }
            if candidate_ids:
                kwargs["where"] = {"resume_identity": {"$in": [str(item) for item in candidate_ids if str(item).strip()]}}
            result = collection.query(**kwargs)
        except Exception as error:
            return {"rows": [], "warnings": [f"{type(error).__name__}: {error}"]}
        ids = list((result.get("ids") or [[]])[0] or [])
        documents = list((result.get("documents") or [[]])[0] or [])
        metadatas = list((result.get("metadatas") or [[]])[0] or [])
        distances = list((result.get("distances") or [[]])[0] or [])
        rows: List[Dict[str, Any]] = []
        for index, vector_id in enumerate(ids):
            metadata = dict(metadatas[index] if index < len(metadatas) and metadatas[index] else {})
            rows.append(
                {
                    "vector_id": str(vector_id),
                    "chunk_text": str(documents[index] if index < len(documents) else ""),
                    "metadata": metadata,
                    "distance": float(distances[index]) if index < len(distances) and distances[index] is not None else None,
                    "rank": index + 1,
                }
            )
        return {"rows": rows, "warnings": warnings}

    def health(self) -> Dict[str, Any]:
        if not self.persist_dir.exists():
            return {"ok": False, "path": str(self.persist_dir), "collection": self.collection_name, "count": 0}
        try:
            collection = self._collection()
            return {"ok": True, "path": str(self.persist_dir), "collection": self.collection_name, "count": collection.count()}
        except Exception as error:
            return {"ok": False, "path": str(self.persist_dir), "collection": self.collection_name, "error": f"{type(error).__name__}: {error}"}

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


def _embed_query_bge_m3(query: str, warnings: List[str]) -> List[float]:
    try:
        from llama_index.embeddings.ollama import OllamaEmbedding

        embedder = OllamaEmbedding(
            model_name=os.getenv("RESUME_V3_EMBED_MODEL", "bge-m3").strip() or "bge-m3",
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip() or "http://localhost:11434",
            client_kwargs={"trust_env": False, "timeout": float(os.getenv("OLLAMA_TIMEOUT", "120") or 120)},
        )
        return list(embedder.get_query_embedding(query) or [])
    except Exception as error:
        warnings.append(f"{type(error).__name__}: {error}")
        return []
