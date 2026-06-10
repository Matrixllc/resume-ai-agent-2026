from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import chromadb

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.runtime.document_parser import parse_resume_to_blocks_with_diagnostics
from resume_query_v3.scripts.create_domain_seed_resumes import DOCUMENTS_DIR, DOMAIN_RESUMES, V3_RESUME_DIR


DOMAIN_EXPECTATIONS = {
    "Operations": {
        "names": {"林妍", "许泽", "唐薇", "韩子墨", "顾婉清"},
        "terms": ["Operations", "运营", "用户运营", "增长运营", "活动运营", "商家运营", "会员运营"],
    },
    "Energy": {
        "names": {"秦昊", "罗雨晴", "何嘉诚", "蒋安然", "叶晨"},
        "terms": ["Energy", "能源", "新能源", "光伏", "风电", "储能", "电力交易", "碳排放"],
    },
    "Finance": {
        "names": {"陈思远", "郭明昊", "孙可欣", "刘嘉宁", "周雨桐"},
        "terms": ["Finance", "金融", "风控", "量化", "投研", "基金", "交易"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate v3 parser, SQLite, and Chroma ingestion integrity for domain seed resumes.")
    parser.add_argument("--directory", default=str(V3_RESUME_DIR), help="Seed resume directory to validate. Defaults to frontend ingestion directory.")
    parser.add_argument("--no-vector", action="store_true", help="Skip Chroma vector row assertions.")
    parser.add_argument("--no-parse", action="store_true", help="Skip parser re-read assertions.")
    args = parser.parse_args()

    config = get_config()
    failures: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    source_dir = Path(args.directory).expanduser()
    if not source_dir.is_absolute():
        source_dir = REPO_ROOT / source_dir
    warnings.extend(_temporary_file_warnings(source_dir))

    for seed in DOMAIN_RESUMES:
        expected_name = str(seed["name"])
        expected_file = str(seed["file"])
        expected_domain, expected_terms = _expected_domain(expected_name)
        file_path = source_dir / expected_file
        row: dict[str, Any] = {
            "file": expected_file,
            "expected_name": expected_name,
            "expected_domain": expected_domain,
        }
        consistency = _check_backup_hash_consistency(file_path, DOCUMENTS_DIR / expected_file)
        row["source_consistency"] = consistency
        failures.extend(f"{expected_file}: {item}" for item in consistency["failures"])
        if not file_path.exists():
            failures.append(f"{expected_file}: source document missing")
            rows.append(row)
            continue
        if not args.no_parse:
            parse_result = _check_parser(file_path, expected_name, config)
            row["parser"] = parse_result
            failures.extend(f"{expected_file}: {item}" for item in parse_result["failures"])

        sql_result = _check_sql(file_path, expected_name, expected_domain, expected_terms, config)
        row["sql"] = sql_result
        failures.extend(f"{expected_file}: {item}" for item in sql_result["failures"])

        if not args.no_vector:
            vector_result = _check_vector(sql_result.get("resume_identity", ""), config)
            row["vector"] = vector_result
            failures.extend(f"{expected_file}: {item}" for item in vector_result["failures"])
        rows.append(row)

    report = {
        "passed": not failures,
        "total": len(rows),
        "directory": str(source_dir),
        "vector_required": not args.no_vector,
        "rows": rows,
        "warnings": warnings,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def _temporary_file_warnings(source_dir: Path) -> list[str]:
    if not source_dir.exists():
        return []
    return [f"ignored temporary file: {path.name}" for path in sorted(source_dir.iterdir()) if path.is_file() and path.name.startswith("~$")]


def _check_backup_hash_consistency(source_path: Path, backup_path: Path) -> dict[str, Any]:
    failures: list[str] = []
    source_hash = _sha256(source_path) if source_path.exists() else ""
    backup_hash = _sha256(backup_path) if backup_path.exists() else ""
    if source_hash and backup_hash and source_hash != backup_hash:
        failures.append(f"backup hash mismatch: {source_path} != {backup_path}")
    return {
        "source_path": str(source_path),
        "backup_path": str(backup_path),
        "backup_exists": backup_path.exists(),
        "same_hash": bool(source_hash and backup_hash and source_hash == backup_hash),
        "source_hash": source_hash,
        "backup_hash": backup_hash,
        "failures": failures,
    }


def _check_parser(file_path: Path, expected_name: str, config: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    try:
        blocks, diag = parse_resume_to_blocks_with_diagnostics(file_path, config)
    except Exception as error:
        return {"ok": False, "failures": [f"parser failed: {type(error).__name__}: {error}"]}
    texts = [block.text.strip() for block in blocks if block.text.strip()]
    if len(texts) < 20:
        failures.append(f"parser block count too low: {len(texts)}")
    if expected_name not in "\n".join(texts[:8]):
        failures.append(f"expected name {expected_name} not found in first parser blocks")
    for heading in ("基本信息", "专业技能", "项目经历", "教育背景"):
        if not any(heading in text for text in texts):
            failures.append(f"parser missing heading {heading}")
    return {
        "ok": not failures,
        "parser_mode": str(diag.get("parser_mode", "")),
        "parser_fallback_reason": str(diag.get("parser_fallback_reason", "")),
        "block_count": len(texts),
        "first_blocks": texts[:5],
        "failures": failures,
    }


def _check_sql(file_path: Path, expected_name: str, expected_domain: str, expected_terms: list[str], config: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    db_path = Path(config["paths"]["structured_store_file"])
    if not db_path.exists():
        return {"ok": False, "failures": [f"structured db missing: {db_path}"]}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        candidates = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM candidates WHERE source_path LIKE ? ORDER BY id",
                (f"%/{file_path.name}",),
            ).fetchall()
        ]
        if not candidates:
            candidates = [dict(row) for row in conn.execute("SELECT * FROM candidates WHERE name = ? ORDER BY id", (expected_name,)).fetchall()]
        if len(candidates) != 1:
            failures.append(f"expected exactly one candidate row, got {len(candidates)}")
            candidate = candidates[-1] if candidates else {}
        else:
            candidate = candidates[0]
        resume_identity = str(candidate.get("resume_identity", "") or "")
        actual_name = str(candidate.get("name", "") or "")
        if actual_name != expected_name:
            failures.append(f"candidate name mismatch: expected {expected_name}, got {actual_name}")
        if str(Path(str(candidate.get("source_path", "") or "")).name) != file_path.name:
            failures.append(f"source_path mismatch: {candidate.get('source_path', '')}")
        elif Path(str(candidate.get("source_path", "") or "")).resolve() != file_path.resolve():
            failures.append(f"source_path directory mismatch: expected {file_path}, got {candidate.get('source_path', '')}")
        projects = _fetch_all(conn, "SELECT * FROM project_manifest WHERE resume_identity = ? ORDER BY id", resume_identity)
        educations = _fetch_all(conn, "SELECT * FROM education_experiences WHERE resume_identity = ? ORDER BY id", resume_identity)
        candidate_tags = _fetch_all(conn, "SELECT * FROM candidate_tags WHERE resume_identity = ? ORDER BY id", resume_identity)
        project_tags = _fetch_all(conn, "SELECT * FROM project_tags WHERE resume_identity = ? ORDER BY id", resume_identity)
    if len(projects) < 2:
        failures.append(f"project rows too low: {len(projects)}")
    if len(educations) < 1:
        failures.append("education rows missing")
    haystack = _joined_text([candidate], projects, candidate_tags, project_tags)
    if expected_domain and not any(term.lower() in haystack.lower() for term in expected_terms):
        failures.append(f"domain evidence missing for {expected_domain}")
    if "基本信息" == actual_name:
        failures.append("candidate name parsed as heading 基本信息")
    return {
        "ok": not failures,
        "resume_identity": resume_identity,
        "name": actual_name,
        "project_count": len(projects),
        "education_count": len(educations),
        "candidate_tag_count": len(candidate_tags),
        "project_tag_count": len(project_tags),
        "sample_projects": [str(item.get("project_name_raw", "")) for item in projects[:3]],
        "failures": failures,
    }


def _check_vector(resume_identity: str, config: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if not resume_identity:
        return {"ok": False, "count": 0, "failures": ["resume_identity missing; cannot check vector rows"]}
    persist_dir = Path(config["paths"]["chroma_dir"])
    collection_name = str(config["storage"].get("chroma_collection", "resume_v3_project_chunks")).strip()
    if not persist_dir.exists():
        return {"ok": False, "count": 0, "failures": [f"chroma dir missing: {persist_dir}"]}
    try:
        client = chromadb.PersistentClient(path=str(persist_dir))
        collection = client.get_or_create_collection(collection_name)
        result = collection.get(where={"resume_identity": resume_identity}, include=["documents", "metadatas"])
    except Exception as error:
        return {"ok": False, "count": 0, "failures": [f"chroma read failed: {type(error).__name__}: {error}"]}
    ids = list(result.get("ids", []) or [])
    documents = list(result.get("documents", []) or [])
    metadatas = list(result.get("metadatas", []) or [])
    if not ids:
        failures.append("vector rows missing for candidate")
    for index, vector_id in enumerate(ids[:5]):
        document = str(documents[index] if index < len(documents) else "")
        metadata = dict(metadatas[index] if index < len(metadatas) and metadatas[index] else {})
        if not document.strip():
            failures.append(f"vector {vector_id} missing document text")
        if str(metadata.get("resume_identity", "") or "") != resume_identity:
            failures.append(f"vector {vector_id} resume_identity metadata mismatch")
        if not str(metadata.get("project_id", "") or "").strip():
            failures.append(f"vector {vector_id} missing project_id metadata")
    return {
        "ok": not failures,
        "count": len(ids),
        "sample_ids": [str(item) for item in ids[:3]],
        "failures": failures,
    }


def _expected_domain(name: str) -> tuple[str, list[str]]:
    for domain, cfg in DOMAIN_EXPECTATIONS.items():
        if name in cfg["names"]:
            return domain, list(cfg["terms"])
    return "", []


def _fetch_all(conn: sqlite3.Connection, sql: str, resume_identity: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, (resume_identity,)).fetchall()]


def _joined_text(*row_groups: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for rows in row_groups:
        for row in rows:
            parts.extend(str(value) for value in row.values() if value not in (None, ""))
    return "\n".join(parts)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
