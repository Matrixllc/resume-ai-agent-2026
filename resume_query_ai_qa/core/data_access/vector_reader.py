from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import chromadb

from resume_query_common import get_resume_embedding_config
from resume_query_common.env import load_repo_env


class ResumeVectorReader:
    """封装项目片段向量库的只读访问，并把检索故障转换为可回退警告。"""
    def __init__(self, *, persist_dir: Path, collection_name: str):
        """初始化实例所需配置。"""
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name

    def list_project_chunks(self, resume_identity: str) -> List[Dict[str, Any]]:
        """按候选人列出项目向量片段，向量库不可读时返回空集合。"""
        if not self.persist_dir.exists():
            return []
        collection = self._collection()
        try:
            result = collection.get(where={"resume_identity": resume_identity}, include=["documents", "metadatas"])
        except Exception:
            # 这是证据补充读取，不参与安全决策；调用方会把空集合当作“未取到向量证据”处理。
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
        """根据查询向量检索项目片段。

        该方法保持只读；向量化或向量检索失败时返回警告，供调用方回退到结构化召回。
        """
        warnings: List[str] = []
        if not self.persist_dir.exists():
            return {"rows": [], "warnings": [f"chroma path not found: {self.persist_dir}"]}
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
        """返回向量库健康状态；异常会进入 error 字段供运维排查。"""
        if not self.persist_dir.exists():
            return {"ok": False, "path": str(self.persist_dir), "collection": self.collection_name, "count": 0}
        try:
            collection = self._collection()
            return {"ok": True, "path": str(self.persist_dir), "collection": self.collection_name, "count": collection.count()}
        except Exception as error:
            return {"ok": False, "path": str(self.persist_dir), "collection": self.collection_name, "error": f"{type(error).__name__}: {error}"}

    def _collection(self) -> Any:
        """获取集合并返回。"""
        client = chromadb.PersistentClient(path=str(self.persist_dir))
        return client.get_or_create_collection(self.collection_name)


def parse_metadata_list(value: Any) -> List[str]:
    """把 Chroma metadata 中的 JSON 列表解析为字符串列表，坏 JSON 返回空列表。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        loaded = json.loads(str(value or "[]"))
    except Exception:
        # metadata 来自历史入库产物，坏值不能中断问答链路。
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded if str(item).strip()]


def _embed_query(query: str, warnings: List[str]) -> List[float]:
    """Generate a query vector using the same provider as ingestion."""
    load_repo_env()
    config = get_resume_embedding_config()
    provider = str(config.get("provider", "ollama")).strip().lower()
    if provider == "openai":
        return _embed_query_openai(query, config, warnings)
    return _embed_query_ollama(query, config, warnings)


def _embed_query_openai(query: str, config: Dict[str, Any], warnings: List[str]) -> List[float]:
    """调用 OpenAI 生成查询向量，失败时写入 warnings 并返回空向量。"""
    try:
        from langchain_openai import OpenAIEmbeddings

        api_key = str(config.get("openai_api_key", "")).strip()
        if not api_key:
            warnings.append("OPENAI_API_KEY is required for OpenAI query embedding")
            return []
        embedder = OpenAIEmbeddings(
            model=str(config.get("model", "text-embedding-3-small")).strip(),
            api_key=api_key,
            base_url=str(config.get("openai_base_url", "https://api.openai.com/v1")).strip(),
        )
        return list(embedder.embed_query(query) or [])
    except Exception as error:
        warnings.append(f"{type(error).__name__}: {error}")
        return []


def _embed_query_ollama(query: str, config: Dict[str, Any], warnings: List[str]) -> List[float]:
    """调用本地 embedding 模型生成查询向量，失败时写入 warnings 并返回空向量。"""
    try:
        from llama_index.embeddings.ollama import OllamaEmbedding

        embedder = OllamaEmbedding(
            model_name=str(config.get("model", "bge-m3")).strip() or "bge-m3",
            base_url=str(config.get("ollama_host", "http://localhost:11434")).strip() or "http://localhost:11434",
            client_kwargs={"trust_env": False, "timeout": float(config.get("ollama_timeout", 120.0) or 120)},
        )
        return list(embedder.get_query_embedding(query) or [])
    except Exception as error:
        warnings.append(f"{type(error).__name__}: {error}")
        return []
