from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Protocol

import chromadb

from .structured_store import StructuredStore


class StructuredBackend(Protocol):
    def upsert(self, payload: Dict[str, Any]) -> bool: ...


class VectorBackend(Protocol):
    def upsert_chunk_vectors(self, payloads: List[Dict[str, Any]]) -> None: ...
    def replace_resume_chunk_vectors(self, resume_identity: str, payloads: List[Dict[str, Any]]) -> None: ...


class SqliteStructuredBackend:
    def __init__(self, db_path: Path):
        self.store = StructuredStore(db_path)

    def upsert(self, payload: Dict[str, Any]) -> bool:
        return self.store.upsert(payload)


class JsonStructuredBackend:
    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def upsert(self, payload: Dict[str, Any]) -> bool:
        replaced_existing = self.file_path.exists()
        self.file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return replaced_existing


class JsonVectorBackend:
    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_chunk_vectors(self, payloads: List[Dict[str, Any]]) -> None:
        self.file_path.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")

    def replace_resume_chunk_vectors(self, resume_identity: str, payloads: List[Dict[str, Any]]) -> None:
        existing: List[Dict[str, Any]] = []
        if self.file_path.exists():
            try:
                loaded = json.loads(self.file_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    existing = loaded
            except Exception:
                existing = []
        retained = [item for item in existing if str(item.get("resume_identity", "")).strip() != resume_identity]
        self.file_path.write_text(json.dumps([*retained, *payloads], ensure_ascii=False, indent=2), encoding="utf-8")


class ChromaVectorBackend:
    def __init__(self, *, persist_dir: Path, collection_name: str):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = self._create_client()
        self._collection = self._client.get_or_create_collection(name=collection_name)

    def upsert_chunk_vectors(self, payloads: List[Dict[str, Any]]) -> None:
        ids: List[str] = []
        embeddings: List[List[float]] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in payloads:
            chunk_id = str(item.get("chunk_id", "")).strip()
            text = str(item.get("chunk_text", "")).strip()
            embedding = list(item.get("embedding", []) or [])
            if not chunk_id or not text or not embedding:
                continue
            vector_id = str(item.get("vector_id", "")).strip() or chunk_id
            if vector_id in seen_ids:
                continue
            seen_ids.add(vector_id)
            ids.append(vector_id)
            embeddings.append(embedding)
            documents.append(text)
            metadatas.append(
                {
                    "project_title": str(item.get("project_title", "") or item.get("chunk_title", "")).strip(),
                    "project_summary": str(item.get("project_summary", "")).strip(),
                    "source_section": str(item.get("source_section", "")).strip(),
                    "organization_raw": str(item.get("organization_raw", "")).strip(),
                    "date_range_raw": str(item.get("date_range_raw", "")).strip(),
                    "project_tags": json.dumps([tag.get("value", "") for tag in list(item.get("project_tags", []) or [])], ensure_ascii=False),
                    "evidence_block_ids": json.dumps(list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []), ensure_ascii=False),
                    "embedding_model": str(item.get("embedding_model", "")).strip(),
                    "resume_identity": str(item.get("resume_identity", "")).strip(),
                    "project_id": str(item.get("project_id", "")).strip(),
                    "schema_version": str(item.get("schema_version", "v3_project_chunk_1")).strip(),
                }
            )
        if ids:
            self._collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def replace_resume_chunk_vectors(self, resume_identity: str, payloads: List[Dict[str, Any]]) -> None:
        identity = str(resume_identity).strip()
        existing_ids: List[str] = []
        if identity:
            try:
                existing = self._collection.get(where={"resume_identity": identity})
                existing_ids = [str(item) for item in list(existing.get("ids", []) or [])]
            except Exception:
                existing_ids = []
        writable_payloads = [
            item
            for item in payloads
            if str(item.get("chunk_text", "")).strip()
            and list(item.get("embedding", []) or [])
            and str(item.get("vector_id", "") or item.get("chunk_id", "")).strip()
        ]
        if not writable_payloads:
            if existing_ids:
                try:
                    self._collection.delete(ids=existing_ids)
                except Exception:
                    pass
            return
        self.upsert_chunk_vectors(writable_payloads)
        current_ids = {str(item.get("vector_id", "") or item.get("chunk_id", "")).strip() for item in writable_payloads}
        stale_ids = [item for item in existing_ids if item not in current_ids]
        if stale_ids:
            try:
                self._collection.delete(ids=stale_ids)
            except Exception:
                pass

    def _create_client(self) -> chromadb.PersistentClient:
        try:
            return chromadb.PersistentClient(
                path=str(self.persist_dir),
                tenant="default_tenant",
                database="default_database",
            )
        except Exception:
            return chromadb.PersistentClient(path=str(self.persist_dir))


def build_structured_backend(config: Dict[str, Any]) -> StructuredBackend:
    backend_name = str(config.get("storage", {}).get("structured_backend", "sqlite")).strip().lower()
    if backend_name == "sqlite":
        return SqliteStructuredBackend(Path(config["paths"]["structured_store_file"]))
    return JsonStructuredBackend(Path(config["paths"]["structured_store_file"]).with_suffix(".json"))


def build_vector_backend(config: Dict[str, Any]) -> VectorBackend:
    backend_name = str(config.get("storage", {}).get("vector_backend", "chroma")).strip().lower()
    if backend_name == "chroma":
        try:
            return ChromaVectorBackend(
                persist_dir=Path(config["paths"]["chroma_dir"]),
                collection_name=str(config["storage"].get("chroma_collection", "resume_v3_project_chunks")).strip(),
            )
        except Exception:
            return JsonVectorBackend(Path(config["paths"]["vector_payload_file"]))
    return JsonVectorBackend(Path(config["paths"]["vector_payload_file"]))
