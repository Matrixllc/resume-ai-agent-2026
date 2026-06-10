from __future__ import annotations

from threading import Lock
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.pipeline import run_ingestion_pipeline

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
_INGESTION_LOCK = Lock()
_STATUS_LOCK = Lock()
_INGESTION_STATUS: Dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "directory": "",
    "total_files": 0,
    "current_index": 0,
    "current_file": "",
    "current_step": "",
    "success_count": 0,
    "error_count": 0,
    "message": "尚未开始导入。",
    "recent_messages": [],
}


class IngestResumesRequest(BaseModel):
    directory: str = "resume_query_v3/resume"
    extensions: List[str] = Field(default_factory=lambda: [".pdf", ".docx", ".doc"])


@router.post("/resumes")
def ingest_resumes(request: IngestResumesRequest | None = None) -> dict:
    if not _INGESTION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有 resume 导入任务正在运行，请等当前任务结束后再试。")
    try:
        return _ingest_resumes(request)
    finally:
        _INGESTION_LOCK.release()


@router.get("/status")
def ingestion_status() -> dict:
    with _STATUS_LOCK:
        return dict(_INGESTION_STATUS)


def _ingest_resumes(request: IngestResumesRequest | None = None) -> dict:
    payload = request or IngestResumesRequest()
    repo_root = Path(__file__).resolve().parents[2]
    target_dir = Path(payload.directory).expanduser()
    if not target_dir.is_absolute():
        target_dir = repo_root / target_dir
    extensions = {item.lower() if item.startswith(".") else f".{item.lower()}" for item in payload.extensions}
    files = []
    if target_dir.exists():
        files = [
            item
            for item in sorted(target_dir.iterdir())
            if item.is_file()
            and item.suffix.lower() in extensions
            and not item.name.startswith("~$")
        ]
    config = get_config()
    results: List[Dict[str, Any]] = []
    _set_status(
        running=True,
        phase="running",
        directory=str(target_dir),
        total_files=len(files),
        current_index=0,
        current_file="",
        current_step="准备扫描 resume 文件",
        success_count=0,
        error_count=0,
        message=f"准备导入 {len(files)} 个文件。",
        recent_messages=[],
    )
    for file_path in files:
        current_index = len(results) + 1
        _set_status(
            current_index=current_index,
            current_file=file_path.name,
            current_step="开始解析",
            message=f"正在处理 {current_index}/{len(files)}：{file_path.name}",
        )
        try:
            result = run_ingestion_pipeline(
                file_path=file_path.resolve(),
                config=config,
                progress_callback=lambda message, file_name=file_path.name: _record_progress(file_name, message),
            )
            results.append(_summary_payload(file_path, result))
            _set_status(
                success_count=len([item for item in results if item.get("status") == "ok"]),
                error_count=len([item for item in results if item.get("status") == "error"]),
                current_step="当前文件完成",
                message=f"{file_path.name} 导入完成。",
            )
        except Exception as error:
            results.append(
                {
                    "file": str(file_path),
                    "status": "error",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            _set_status(
                success_count=len([item for item in results if item.get("status") == "ok"]),
                error_count=len([item for item in results if item.get("status") == "error"]),
                current_step="当前文件失败",
                message=f"{file_path.name} 导入失败：{type(error).__name__}: {error}",
            )
    final_message = _build_ingestion_message(target_dir=target_dir, files=files, results=results)
    _set_status(
        running=False,
        phase="done",
        current_step="导入完成",
        current_file="",
        message=final_message,
        success_count=len([item for item in results if item.get("status") == "ok"]),
        error_count=len([item for item in results if item.get("status") == "error"]),
    )
    return {
        "directory": str(target_dir),
        "total_files": len(files),
        "success_count": len([item for item in results if item.get("status") == "ok"]),
        "error_count": len([item for item in results if item.get("status") == "error"]),
        "message": final_message,
        "results": results,
    }


def _record_progress(file_name: str, message: str) -> None:
    _set_status(current_file=file_name, current_step=str(message), message=f"{file_name}: {message}")


def _set_status(**updates: Any) -> None:
    with _STATUS_LOCK:
        _INGESTION_STATUS.update(updates)
        message = str(updates.get("message", "")).strip()
        if message:
            recent = list(_INGESTION_STATUS.get("recent_messages", []) or [])
            recent.append(message)
            _INGESTION_STATUS["recent_messages"] = recent[-8:]


def _summary_payload(file_path: Path, result: dict) -> dict:
    storage_summary = dict(result.get("storage_summary", {}) or {})
    storage_gate = dict(result.get("storage_gate", {}) or {})
    stored_project_rows = len(list(storage_summary.get("project_manifest_rows", []) or []))
    return {
        "file": str(file_path),
        "status": "ok",
        "run_id": result.get("run_meta", {}).get("run_id", ""),
        "resume_identity": result.get("run_meta", {}).get("resume_identity", ""),
        "replaced_existing_resume": bool(result.get("run_meta", {}).get("replaced_existing_resume", False)),
        "prior_run_count": int(result.get("run_meta", {}).get("prior_run_count", 0) or 0),
        "resolve_mode": result.get("run_meta", {}).get("resolve_mode", ""),
        "document_profile": dict(result.get("document_profile", {}) or {}).get("value", ""),
        "name": dict(result.get("candidate_profile", {}).get("name", {}) or {}).get("value", ""),
        "work_count": len(result.get("work_experiences", []) or []),
        "education_count": len(result.get("education_experiences", []) or []),
        "project_count": stored_project_rows if storage_gate.get("storage_blocked_reason") else result.get("project_count", len(result.get("project_chunks", []) or [])),
        "stored_project_rows": stored_project_rows,
        "stored_vector_rows": len(list(storage_summary.get("vector_rows", []) or [])),
        "storage_blocked_reason": storage_gate.get("storage_blocked_reason", ""),
        "storage_blocked_message": _storage_blocked_message(str(storage_gate.get("storage_blocked_reason", "") or "")),
    }


def _build_ingestion_message(*, target_dir: Path, files: List[Path], results: List[Dict[str, Any]]) -> str:
    if not target_dir.exists():
        return f"扫描目录不存在：{target_dir}"
    if not files:
        return f"扫描目录没有可处理的简历文件：{target_dir}"
    success_count = len([item for item in results if item.get("status") == "ok"])
    error_count = len([item for item in results if item.get("status") == "error"])
    blocked = [
        str(item.get("storage_blocked_reason", "")).strip()
        for item in results
        if str(item.get("storage_blocked_reason", "")).strip()
    ]
    if blocked:
        return f"扫描完成，但有 {len(blocked)} 个文件项目边界未可信完成，项目未入库；候选人基础信息仍会写入。"
    return f"扫描完成：{success_count}/{len(files)} 成功，{error_count} 失败。"


def _storage_blocked_message(reason: str) -> str:
    if reason == "project_boundary_not_trusted":
        return "项目边界未可信完成，项目未入库。"
    if reason == "low_quality_project_boundary":
        return "项目边界质量过低，项目未入库。"
    if reason:
        return f"项目未入库：{reason}"
    return ""
