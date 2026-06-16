from __future__ import annotations

import hashlib
import re
import shutil
from threading import Lock
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.pipeline import run_ingestion_pipeline
from resume_query_v3.core.data_layer.storage.backends import clear_chroma_system_cache

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
_INGESTION_LOCK = Lock()
_STATUS_LOCK = Lock()
_INGESTION_STATUS: Dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "mode": "",
    "directory": "",
    "uploaded_file": "",
    "total_files": 0,
    "current_index": 0,
    "current_file": "",
    "current_step": "",
    "success_count": 0,
    "error_count": 0,
    "message": "尚未开始导入。",
    "error_hint": "",
    "recent_messages": [],
}


class IngestResumesRequest(BaseModel):
    directory: str = "resume"
    extensions: List[str] = Field(default_factory=lambda: [".pdf", ".docx", ".doc"])
    reset_before_ingest: bool = True


@router.post("/resumes")
def ingest_resumes(request: IngestResumesRequest | None = None) -> dict:
    if not _INGESTION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有 resume 导入任务正在运行，请等当前任务结束后再试。")
    try:
        return _ingest_resumes(request)
    finally:
        _INGESTION_LOCK.release()


@router.post("/resumes/clear")
def clear_resumes() -> dict:
    if not _INGESTION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有导入或清空任务正在运行，请等待当前任务完成。")
    try:
        return _clear_resumes()
    finally:
        _INGESTION_LOCK.release()


@router.post("/resumes/upload")
async def upload_resume(file: UploadFile = File(...)) -> dict:
    if not _INGESTION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有 resume 导入任务正在运行，请等当前任务结束后再试。")
    try:
        return await _upload_resume(file)
    finally:
        _INGESTION_LOCK.release()


@router.get("/status")
def ingestion_status() -> dict:
    with _STATUS_LOCK:
        return dict(_INGESTION_STATUS)


def _ingest_resumes(request: IngestResumesRequest | None = None) -> dict:
    payload = request or IngestResumesRequest()
    config = get_config()
    target_dir = _resolve_resume_directory(payload.directory, config)
    extensions = {item.lower() if item.startswith(".") else f".{item.lower()}" for item in payload.extensions}
    _seed_configured_resume_dir(config=config, target_dir=target_dir, extensions=extensions)
    files = []
    if target_dir.exists():
        files = [
            item
            for item in sorted(target_dir.iterdir())
            if item.is_file()
            and item.suffix.lower() in extensions
            and not item.name.startswith("~$")
        ]
    reset_summary: Dict[str, Any] = {"enabled": bool(payload.reset_before_ingest), "removed": [], "skipped_missing": []}
    results: List[Dict[str, Any]] = []
    _set_status(
        running=True,
        phase="running",
        mode="directory",
        directory=str(target_dir),
        uploaded_file="",
        total_files=len(files),
        current_index=0,
        current_file="",
        current_step="准备扫描 resume 文件",
        success_count=0,
        error_count=0,
        message=f"准备导入 {len(files)} 个文件。",
        error_hint="",
        recent_messages=[],
    )
    if payload.reset_before_ingest:
        _set_status(
            current_step="清空旧入库数据",
            message="正在删除旧 SQLite 数据库和 Chroma 向量库，准备重新批量入库。",
        )
        reset_summary = _reset_ingestion_storage(config)
        removed_count = len(reset_summary.get("removed", []) or [])
        _set_status(
            current_step="旧数据清理完成",
            message=f"旧入库数据清理完成：删除 {removed_count} 项，开始批量入库。",
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
            friendly_error = _friendly_ingestion_error(error)
            results.append(
                {
                    "file": str(file_path),
                    "status": "error",
                    "error": friendly_error,
                }
            )
            _set_status(
                success_count=len([item for item in results if item.get("status") == "ok"]),
                error_count=len([item for item in results if item.get("status") == "error"]),
                current_step="当前文件失败",
                error_hint=friendly_error,
                message=f"{file_path.name} 导入失败：{friendly_error}",
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
        error_hint="",
    )
    return {
        "directory": str(target_dir),
        "total_files": len(files),
        "success_count": len([item for item in results if item.get("status") == "ok"]),
        "error_count": len([item for item in results if item.get("status") == "error"]),
        "message": final_message,
        "reset_summary": reset_summary,
        "results": results,
    }


def _clear_resumes() -> dict:
    config = get_config()
    resume_dir = Path(config.get("paths", {}).get("resume_dir") or "")
    _set_status(
        running=True,
        phase="running",
        mode="clear",
        directory=str(resume_dir),
        uploaded_file="",
        total_files=0,
        current_index=0,
        current_file="",
        current_step="清空候选人库",
        success_count=0,
        error_count=0,
        message="正在清空候选人库...",
        error_hint="",
        recent_messages=["正在清空候选人库..."],
    )
    try:
        reset_summary = _reset_ingestion_storage(config)
        uploads_summary = _clear_uploads(config)
    except Exception as error:
        friendly_error = _friendly_ingestion_error(error)
        _set_status(
            running=False,
            phase="done",
            current_step="清空候选人库失败",
            success_count=0,
            error_count=1,
            error_hint=friendly_error,
            message=f"清空候选人库失败：{friendly_error}",
        )
        raise
    reset_summary["uploads_removed"] = uploads_summary["removed"]
    reset_summary["uploads_skipped_missing"] = uploads_summary["skipped_missing"]
    message = (
        "已清空候选人库："
        f"删除 {len(reset_summary.get('removed', []) or [])} 项 SQLite/Chroma 存储，"
        f"删除 {len(reset_summary.get('uploads_removed', []) or [])} 个上传文件。"
    )
    _set_status(
        running=False,
        phase="done",
        current_step="清空候选人库完成",
        success_count=0,
        error_count=0,
        error_hint="",
        message=message,
    )
    return {
        "directory": str(resume_dir),
        "total_files": 0,
        "success_count": 0,
        "error_count": 0,
        "message": message,
        "reset_summary": reset_summary,
        "results": [],
    }


async def _upload_resume(file: UploadFile) -> dict:
    config = get_config()
    upload_config = dict(config.get("upload", {}) or {})
    max_upload_bytes = int(upload_config.get("max_upload_bytes", 20 * 1024 * 1024) or 20 * 1024 * 1024)
    allowed_extensions = {
        str(item).lower() if str(item).startswith(".") else f".{str(item).lower()}"
        for item in (upload_config.get("allowed_extensions") or [".pdf", ".docx", ".doc"])
    }
    original_name = Path(file.filename or "").name.strip()
    if not original_name:
        raise HTTPException(status_code=400, detail="请选择要上传的简历文件。")
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"暂不支持 {suffix or '无扩展名'} 文件，请上传 pdf/doc/docx。")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    if len(content) > max_upload_bytes:
        limit_mb = max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"上传文件超过 {limit_mb}MB 限制。")

    upload_dir = _resolve_upload_dir(upload_config.get("resume_upload_dir"), config)
    upload_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    safe_name = _safe_upload_name(original_name)
    target_path = (upload_dir / f"{digest[:12]}_{safe_name}").resolve()
    if not _is_relative_to(target_path, upload_dir):
        raise HTTPException(status_code=400, detail="上传文件名非法。")
    target_path.write_bytes(content)
    _set_status(
        running=True,
        phase="running",
        mode="upload",
        directory=str(upload_dir),
        uploaded_file=target_path.name,
        total_files=1,
        current_index=1,
        current_file=target_path.name,
        current_step="保存上传文件",
        success_count=0,
        error_count=0,
        error_hint="",
        message=f"已保存上传文件：{target_path.name}",
        recent_messages=[],
    )

    _set_status(
        running=True,
        phase="running",
        mode="upload",
        directory=str(upload_dir),
        uploaded_file=target_path.name,
        total_files=1,
        current_index=1,
        current_file=target_path.name,
        current_step="开始解析上传简历",
        success_count=0,
        error_count=0,
        error_hint="",
        message=f"正在解析上传简历：{target_path.name}",
    )
    try:
        result = await run_in_threadpool(
            lambda: run_ingestion_pipeline(
                file_path=target_path,
                config=config,
                progress_callback=lambda message: _record_progress(target_path.name, message),
            )
        )
        summary = _summary_payload(target_path, result)
        _set_status(
            running=False,
            phase="done",
            current_step="上传入库完成",
            current_file="",
            success_count=1,
            error_count=0,
            error_hint="",
            message=f"{target_path.name} 上传并入库完成。",
        )
        return {
            "directory": str(upload_dir),
            "uploaded_file": target_path.name,
            "original_file": original_name,
            "stored_file": str(target_path),
            "total_files": 1,
            "success_count": 1,
            "error_count": 0,
            "message": f"{target_path.name} 上传并入库完成。",
            "results": [summary],
        }
    except Exception as error:
        friendly_error = _friendly_ingestion_error(error)
        error_payload = {
            "file": str(target_path),
            "status": "error",
            "error": friendly_error,
        }
        _set_status(
            running=False,
            phase="done",
            current_step="上传入库失败",
            current_file="",
            success_count=0,
            error_count=1,
            error_hint=friendly_error,
            message=f"{target_path.name} 上传成功但入库失败：{friendly_error}",
        )
        return {
            "directory": str(upload_dir),
            "uploaded_file": target_path.name,
            "original_file": original_name,
            "stored_file": str(target_path),
            "total_files": 1,
            "success_count": 0,
            "error_count": 1,
            "message": f"{target_path.name} 上传成功但入库失败：{friendly_error}",
            "results": [error_payload],
        }


def _record_progress(file_name: str, message: str) -> None:
    display = _display_progress_message(message)
    _set_status(current_file=file_name, current_step=display, message=f"{file_name}: {display}")


def _reset_ingestion_storage(config: Dict[str, Any]) -> Dict[str, Any]:
    paths = dict(config.get("paths", {}) or {})
    targets = [
        Path(paths["structured_store_file"]),
        Path(paths["jobs_db"]),
        Path(paths["vector_payload_file"]),
        Path(paths["chroma_dir"]),
    ]
    report: Dict[str, Any] = {
        "enabled": True,
        "removed": [],
        "skipped_missing": [],
        "recreated_dirs": [],
    }
    clear_chroma_system_cache()
    for target in targets:
        target = target.resolve()
        if not target.exists():
            report["skipped_missing"].append(str(target))
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        report["removed"].append(str(target))
    for directory in _storage_directories_to_recreate(config):
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        report["recreated_dirs"].append(str(directory))
    clear_chroma_system_cache()
    return report


def _clear_uploads(config: Dict[str, Any]) -> Dict[str, Any]:
    paths = dict(config.get("paths", {}) or {})
    upload = dict(config.get("upload", {}) or {})
    resume_dir = Path(paths["resume_dir"])
    upload_dir = Path(upload.get("resume_upload_dir") or resume_dir / "uploads").resolve()
    report: Dict[str, Any] = {"removed": [], "skipped_missing": []}
    if not upload_dir.exists():
        report["skipped_missing"].append(str(upload_dir))
        upload_dir.mkdir(parents=True, exist_ok=True)
        return report
    for item in sorted(upload_dir.iterdir()):
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        report["removed"].append(str(item))
    upload_dir.mkdir(parents=True, exist_ok=True)
    return report


def _storage_directories_to_recreate(config: Dict[str, Any]) -> List[Path]:
    paths = dict(config.get("paths", {}) or {})
    upload = dict(config.get("upload", {}) or {})
    directories = [
        Path(paths["structured_store_file"]).parent,
        Path(paths["jobs_db"]).parent,
        Path(paths["vector_payload_file"]).parent,
        Path(paths["chroma_dir"]),
        Path(paths["resume_dir"]),
        Path(upload.get("resume_upload_dir") or Path(paths["resume_dir"]) / "uploads"),
    ]
    deduped: List[Path] = []
    seen: set[str] = set()
    for directory in directories:
        key = str(directory.resolve())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(directory)
    return deduped


def _set_status(**updates: Any) -> None:
    with _STATUS_LOCK:
        _INGESTION_STATUS.update(updates)
        message = str(updates.get("message", "")).strip()
        if message:
            recent = list(_INGESTION_STATUS.get("recent_messages", []) or [])
            recent.append(message)
            _INGESTION_STATUS["recent_messages"] = recent[-8:]


def _display_progress_message(message: str) -> str:
    raw = str(message or "").strip()
    if raw.startswith("1/6 parse resume blocks"):
        return "解析简历文本"
    if raw.startswith("parser="):
        return f"解析完成：{raw}"
    if raw.startswith("2/6 build rule candidates"):
        return "抽取候选字段和项目边界"
    if raw.startswith("rule profile="):
        return f"规则抽取完成：{raw.replace('rule profile=', '')}"
    if raw.startswith("3/6"):
        return "LLM/规则复核项目边界"
    if raw in {"llm_success", "rule_fallback"} or raw.startswith("rule_fallback"):
        return f"边界复核完成：{raw}"
    if raw.startswith("4/6 validate result"):
        return "校验结构化结果"
    if raw.startswith("5/6 write SQL rows and Chroma vectors"):
        return "写入 SQLite 和向量库"
    if raw.startswith("storage "):
        return f"写库完成：{raw.replace('storage ', '')}"
    if raw.startswith("6/6 write latest/history logs"):
        return "写入审计日志"
    return raw


def _friendly_ingestion_error(error: Exception) -> str:
    raw = f"{type(error).__name__}: {error}"
    lowered = raw.lower()
    if "collection expecting embedding with dimension" in lowered and "got" in lowered:
        return (
            "向量库维度与当前 embedding 模型不一致。"
            "请使用当前模型专属 Chroma collection，或重新入库生成新的向量库。"
        )
    if "embedding generation failed" in lowered:
        if "apiconnectionerror" in lowered or "connection error" in lowered:
            return (
                "向量 embedding 生成失败：无法连接 embedding 服务。"
                "请检查 OPENAI_BASE_URL、OPENAI_API_KEY 和网络连接，"
                "或设置 RESUME_V3_EMBED_PROVIDER=ollama 并启动 Ollama 后重试。"
            )
        if "missing openai_api_key" in lowered or "openai_api_key" in lowered:
            return "向量 embedding 生成失败：缺少 OPENAI_API_KEY，请配置后重启后端再重试。"
        if "not installed" in lowered:
            return "向量 embedding 生成失败：缺少 embedding 依赖包，请安装依赖后重试。"
        return f"向量 embedding 生成失败：{error}"
    if "chroma vector write failed" in lowered or "attempt to write a readonly database" in lowered:
        return (
            "Chroma 向量库写入失败：当前向量库目录或底层 SQLite 不可写。"
            "请确认后端已重启、没有旧进程占用 Chroma，并且数据目录具有写权限；"
            "批量重建会重新创建 Chroma 目录后再写入。"
        )
    if "database is locked" in lowered:
        return "数据库正在被其他进程占用，请停止旧后端进程后重试批量重建。"
    return raw


def _summary_payload(file_path: Path, result: dict) -> dict:
    storage_summary = dict(result.get("storage_summary", {}) or {})
    storage_gate = dict(result.get("storage_gate", {}) or {})
    stored_project_rows = len(list(storage_summary.get("project_manifest_rows", []) or []))
    return {
        "file": str(file_path),
        "status": "ok",
        "run_id": result.get("run_meta", {}).get("run_id", ""),
        "resume_identity": result.get("run_meta", {}).get("resume_identity", ""),
        "document_hash": result.get("run_meta", {}).get("document_hash", ""),
        "identity_match_source": result.get("run_meta", {}).get("identity_match_source", "file_hash"),
        "merged_existing_candidate": bool(result.get("run_meta", {}).get("merged_existing_candidate", False)),
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


def _seed_configured_resume_dir(*, config: Dict[str, Any], target_dir: Path, extensions: set[str]) -> None:
    """Copy repository sample resumes into the configured runtime directory when it is empty."""
    paths = dict(config.get("paths", {}) or {})
    repo_root = Path(paths.get("repo_root") or Path(__file__).resolve().parents[2]).resolve()
    resume_dir = Path(paths.get("resume_dir") or repo_root / "data" / "resume").resolve()
    if target_dir.resolve() != resume_dir or _has_resume_files(target_dir, extensions):
        return
    sample_dir = repo_root / "data" / "resume"
    if sample_dir.resolve() == resume_dir or not sample_dir.exists():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for sample in sorted(sample_dir.iterdir()):
        if not sample.is_file() or sample.suffix.lower() not in extensions or sample.name.startswith("~$"):
            continue
        destination = target_dir / sample.name
        if not destination.exists():
            shutil.copy2(sample, destination)


def _has_resume_files(directory: Path, extensions: set[str]) -> bool:
    if not directory.exists():
        return False
    return any(
        item.is_file() and item.suffix.lower() in extensions and not item.name.startswith("~$")
        for item in directory.iterdir()
    )


def _resolve_resume_directory(directory: str, config: Dict[str, Any]) -> Path:
    repo_root = Path(config.get("paths", {}).get("repo_root") or Path(__file__).resolve().parents[2]).resolve()
    resume_dir = Path(config.get("paths", {}).get("resume_dir") or repo_root / "data" / "resume").resolve()
    normalized = str(directory or "").strip().strip("/")
    if normalized in {"", "resume", "data/resume"}:
        return resume_dir
    target_dir = Path(directory).expanduser()
    if target_dir.is_absolute():
        target_dir = target_dir.resolve()
    else:
        target_dir = (repo_root / target_dir).resolve()
    if target_dir != resume_dir and not _is_relative_to(target_dir, resume_dir):
        raise HTTPException(status_code=400, detail=f"只允许扫描简历目录：{resume_dir}")
    return target_dir


def _resolve_upload_dir(value: Any, config: Dict[str, Any]) -> Path:
    repo_root = Path(config.get("paths", {}).get("repo_root") or Path(__file__).resolve().parents[2]).resolve()
    resume_dir = Path(config.get("paths", {}).get("resume_dir") or repo_root / "data" / "resume").resolve()
    upload_dir = Path(value or resume_dir / "uploads").expanduser()
    if upload_dir.is_absolute():
        upload_dir = upload_dir.resolve()
    else:
        upload_dir = (repo_root / upload_dir).resolve()
    if not _is_relative_to(upload_dir, resume_dir):
        raise HTTPException(status_code=500, detail="上传目录配置必须位于 resume 目录内。")
    return upload_dir


def _safe_upload_name(filename: str) -> str:
    name = Path(filename).name.strip().replace(" ", "_")
    safe = re.sub(r"[^\w.\-]+", "_", name)
    safe = re.sub(r"_+", "_", safe).strip("._-")
    return safe or "resume.pdf"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
