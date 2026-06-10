from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path

import chromadb

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.pipeline import run_ingestion_pipeline
from resume_query_v3.scripts.create_domain_seed_resumes import DOMAIN_RESUMES, V3_RESUME_DIR


SEED_RESUME_DIR = V3_RESUME_DIR

DOMAIN_SEED_FILES = [
    "林妍-用户运营专员.docx",
    "许泽-增长运营经理.docx",
    "唐薇-活动运营经理.docx",
    "韩子墨-商家运营主管.docx",
    "顾婉清-会员运营负责人.docx",
    "秦昊-新能源项目经理.docx",
    "罗雨晴-储能产品运营.docx",
    "何嘉诚-风电运维工程师.docx",
    "蒋安然-电力交易分析师.docx",
    "叶晨-碳资产项目顾问.docx",
    "陈思远-金融产品经理.docx",
    "郭明昊-金融数据分析师.docx",
    "孙可欣-风控运营经理.docx",
    "刘嘉宁-量化研究助理.docx",
    "周雨桐-投研分析师.docx",
]


def main() -> int:
    _configure_logging()
    config = get_config()
    _cleanup_existing_seed_rows(config)
    failures: list[str] = []
    summaries: list[dict] = []
    for file_name in DOMAIN_SEED_FILES:
        path = SEED_RESUME_DIR / file_name
        if not path.exists():
            failures.append(f"missing seed resume: {path}")
            continue
        print(f"[domain_seed_ingest] start {file_name}", file=sys.stderr)
        try:
            result = run_ingestion_pipeline(file_path=path, config=config, progress_callback=lambda message: print(f"[domain_seed_ingest] {file_name} | {message}", file=sys.stderr))
        except Exception as error:
            failures.append(f"{file_name}: {type(error).__name__}: {error}")
            continue
        summaries.append(_summary(result))
    print(json.dumps({"summaries": summaries, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def _cleanup_existing_seed_rows(config: dict) -> None:
    db_path = Path(config["paths"]["structured_store_file"])
    if not db_path.exists():
        return
    seed_names = {str(item.get("name", "")).strip() for item in DOMAIN_RESUMES}
    seed_files = {str(item.get("file", "")).strip() for item in DOMAIN_RESUMES}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT resume_identity, source_path, name FROM candidates").fetchall()
        identities = [
            str(resume_identity)
            for resume_identity, source_path, name in rows
            if Path(str(source_path)).name in seed_files or str(name).strip() in seed_names
        ]
        if not identities:
            return
        placeholders = ",".join("?" for _ in identities)
        for table in ("work_experiences", "education_experiences", "candidate_tags", "project_manifest", "project_tags", "candidates"):
            conn.execute(f"DELETE FROM {table} WHERE resume_identity IN ({placeholders})", identities)
    _cleanup_existing_seed_vectors(config, identities)
    print(f"[domain_seed_ingest] cleaned_existing_seed_rows={len(identities)}", file=sys.stderr)


def _cleanup_existing_seed_vectors(config: dict, identities: list[str]) -> None:
    chroma_dir = Path(config["paths"]["chroma_dir"])
    if not chroma_dir.exists():
        return
    try:
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection = client.get_or_create_collection(str(config["storage"].get("chroma_collection", "resume_v3_project_chunks")).strip())
    except Exception:
        return
    for resume_identity in identities:
        try:
            existing = collection.get(where={"resume_identity": resume_identity})
            ids = [str(item) for item in list(existing.get("ids", []) or [])]
            if ids:
                collection.delete(ids=ids)
        except Exception:
            continue


def _summary(result: dict) -> dict:
    storage_summary = dict(result.get("storage_summary", {}) or {})
    return {
        "name": dict(result.get("candidate_profile", {}).get("name", {}) or {}).get("value", ""),
        "resume_identity": result.get("run_meta", {}).get("resume_identity", ""),
        "project_count": result.get("project_count", len(result.get("project_chunks", []) or [])),
        "stored_project_rows": len(list(storage_summary.get("project_manifest_rows", []) or [])),
        "stored_vector_rows": len(list(storage_summary.get("vector_rows", []) or [])),
        "storage_blocked_reason": dict(result.get("storage_gate", {}) or {}).get("storage_blocked_reason", ""),
    }


def _configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING)
    for logger_name in ("RapidOCR", "rapidocr", "docling", "onnxruntime", "httpx", "openai", "chromadb"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


if __name__ == "__main__":
    raise SystemExit(main())
