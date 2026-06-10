from __future__ import annotations

import json
import urllib.request

from fastapi import APIRouter

from resume_query_v3.config import get_config as get_v3_config
from resume_query_tools.config import get_tools_config
from resume_query_tools.stores.sql_reader import ResumeSqlReader
from resume_query_tools.stores.vector_reader import ResumeVectorReader

from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    config = get_tools_config()
    sql_reader = ResumeSqlReader(config["paths"]["structured_store_file"])
    vector_reader = ResumeVectorReader(
        persist_dir=config["paths"]["chroma_dir"],
        collection_name=config["storage"]["chroma_collection"],
    )
    sql = sql_reader.health()
    vector = vector_reader.health()
    status = "ok" if sql.get("ok") and vector.get("ok") else "degraded"
    return HealthResponse(status=status, sql=sql, vector=vector)


@router.get("/llm/status")
def llm_status() -> dict:
    config = get_v3_config()
    ollama = _check_ollama(config["env"]["ollama_host"])
    chat_provider = str(config["model"]["chat_provider"])
    local_active = chat_provider == "ollama"
    return {
        "chat_provider": chat_provider,
        "display_name": "本地模型" if local_active else "GPT",
        "available": bool(ollama.get("ok")) if local_active else bool(config["env"]["openai_api_key"]),
        "local_available": bool(ollama.get("ok")),
        "message": "当前使用本地模型。" if local_active else "当前使用 GPT；如需本地模型，请设置 RESUME_V3_CHAT_PROVIDER=ollama 并重启后端。",
    }


def _check_ollama(host: str) -> dict:
    base = str(host or "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}", "models": []}
    models = [str(item.get("name", "")).strip() for item in list(payload.get("models", []) or []) if str(item.get("name", "")).strip()]
    return {"ok": True, "models": models}
