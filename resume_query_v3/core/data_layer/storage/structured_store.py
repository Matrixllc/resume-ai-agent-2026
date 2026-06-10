from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


class StructuredStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    resume_identity TEXT NOT NULL UNIQUE,
                    source_path TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    wechat TEXT DEFAULT '',
                    job_intent TEXT DEFAULT '',
                    location_raw TEXT DEFAULT '',
                    overview_raw TEXT DEFAULT '',
                    document_profile TEXT DEFAULT '',
                    resolve_mode TEXT DEFAULT '',
                    compression_ratio REAL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resume_identity TEXT NOT NULL,
                    work_ref TEXT DEFAULT '',
                    company_name TEXT DEFAULT '',
                    job_title_raw TEXT DEFAULT '',
                    start_date TEXT DEFAULT '',
                    end_date TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    raw_line TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    evidence_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS education_experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resume_identity TEXT NOT NULL,
                    school_name TEXT DEFAULT '',
                    degree TEXT DEFAULT '',
                    major TEXT DEFAULT '',
                    start_date TEXT DEFAULT '',
                    end_date TEXT DEFAULT '',
                    raw_line TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    evidence_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resume_identity TEXT NOT NULL,
                    tag_type TEXT NOT NULL,
                    tag_value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.0,
                    evidence_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_manifest (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resume_identity TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    project_name_raw TEXT DEFAULT '',
                    project_source_type TEXT DEFAULT '',
                    parent_work_experience_ref TEXT DEFAULT '',
                    organization_raw TEXT DEFAULT '',
                    date_range_raw TEXT DEFAULT '',
                    role_raw TEXT DEFAULT '',
                    role_normalized TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    evidence_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resume_identity TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    tag_type TEXT NOT NULL,
                    tag_value TEXT NOT NULL,
                    raw_value TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    evidence_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_resume_identity ON candidates(resume_identity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_tags_lookup ON candidate_tags(tag_type, tag_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_manifest_resume ON project_manifest(resume_identity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tags_lookup ON project_tags(tag_type, tag_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tags_resume ON project_tags(resume_identity, project_id)")

    def upsert(self, payload: Dict[str, Any]) -> bool:
        run_meta = dict(payload.get("run_meta", {}) or {})
        candidate_profile = dict(payload.get("candidate_profile", {}) or {})
        resume_identity = str(run_meta.get("resume_identity", "")).strip()
        run_id = str(run_meta.get("run_id", "")).strip()
        if not resume_identity or not run_id:
            raise ValueError("run_id and resume_identity are required")
        with sqlite3.connect(self.db_path) as conn:
            replaced_existing = bool(conn.execute("SELECT 1 FROM candidates WHERE resume_identity = ? LIMIT 1", (resume_identity,)).fetchone())
            contact = dict(candidate_profile.get("contact", {}) or {})
            candidate_values = (
                run_id,
                str(run_meta.get("source_path", "")).strip(),
                str(dict(candidate_profile.get("name", {}) or {}).get("value", "")).strip(),
                str(dict(contact.get("phone", {}) or {}).get("value", "")).strip(),
                str(dict(contact.get("email", {}) or {}).get("value", "")).strip(),
                str(dict(contact.get("wechat", {}) or {}).get("value", "")).strip(),
                str(dict(candidate_profile.get("job_intent", {}) or {}).get("value", "")).strip(),
                str(dict(candidate_profile.get("location_raw", {}) or {}).get("value", "")).strip(),
                str(dict(candidate_profile.get("overview_raw", {}) or {}).get("value", "")).strip(),
                str(dict(payload.get("document_profile", {}) or {}).get("value", "")).strip(),
                str(run_meta.get("resolve_mode", "")).strip(),
                float(run_meta.get("compression_ratio", 0.0) or 0.0),
            )
            if replaced_existing:
                conn.execute(
                    """
                    UPDATE candidates
                    SET
                        run_id = ?,
                        source_path = ?,
                        name = ?,
                        phone = ?,
                        email = ?,
                        wechat = ?,
                        job_intent = ?,
                        location_raw = ?,
                        overview_raw = ?,
                        document_profile = ?,
                        resolve_mode = ?,
                        compression_ratio = ?
                    WHERE resume_identity = ?
                    """,
                    (*candidate_values, resume_identity),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO candidates (
                        run_id, resume_identity, source_path, name, phone, email, wechat, job_intent,
                        location_raw, overview_raw, document_profile, resolve_mode, compression_ratio
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, resume_identity, *candidate_values[1:]),
                )
            for table in ("work_experiences", "education_experiences", "candidate_tags", "project_manifest", "project_tags"):
                conn.execute(f"DELETE FROM {table} WHERE resume_identity = ?", (resume_identity,))
            self._insert_work_experiences(conn, resume_identity, payload.get("work_experiences", []) or [])
            self._insert_education_experiences(conn, resume_identity, payload.get("education_experiences", []) or [])
            self._insert_tags(conn, resume_identity, "concept", payload.get("concept_tags", []) or [])
            self._insert_tags(conn, resume_identity, "domain", payload.get("domain_tags", []) or [])
            self._insert_tags(conn, resume_identity, "experience", payload.get("experience_tags", []) or [])
            self._insert_tags(conn, resume_identity, "skill", payload.get("skill_tags", []) or [])
            self._insert_candidate_profile_tags(conn, resume_identity, candidate_profile)
            self._insert_projects(conn, resume_identity, payload.get("projects", []) or [], payload.get("project_chunks", []) or [])
            return replaced_existing

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    def _insert_work_experiences(self, conn: sqlite3.Connection, resume_identity: str, rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            conn.execute(
                """
                INSERT INTO work_experiences (
                    resume_identity, work_ref, company_name, job_title_raw, start_date, end_date,
                    location, raw_line, confidence, evidence_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_identity,
                    str(row.get("work_ref", "")).strip(),
                    str(row.get("company_name", "")).strip(),
                    str(row.get("job_title_raw", "")).strip(),
                    str(row.get("start_date", "")).strip(),
                    str(row.get("end_date", "")).strip(),
                    str(row.get("location", "")).strip(),
                    str(row.get("raw_line", "")).strip(),
                    float(row.get("confidence", 0.0) or 0.0),
                    json.dumps(row.get("evidence", {}) or {}, ensure_ascii=False),
                    str(row.get("source", "")).strip(),
                ),
            )

    def _insert_education_experiences(self, conn: sqlite3.Connection, resume_identity: str, rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            conn.execute(
                """
                INSERT INTO education_experiences (
                    resume_identity, school_name, degree, major, start_date, end_date, raw_line,
                    confidence, evidence_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_identity,
                    str(row.get("school_name", "")).strip(),
                    str(row.get("degree", "")).strip(),
                    str(row.get("major", "")).strip(),
                    str(row.get("start_date", "")).strip(),
                    str(row.get("end_date", "")).strip(),
                    str(row.get("raw_line", "")).strip(),
                    float(row.get("confidence", 0.0) or 0.0),
                    json.dumps(row.get("evidence", {}) or {}, ensure_ascii=False),
                    str(row.get("source", "")).strip(),
                ),
            )

    def _insert_tags(self, conn: sqlite3.Connection, resume_identity: str, tag_type: str, rows: List[Dict[str, Any]]) -> None:
        seen = set()
        for row in rows:
            tag_value = str(row.get("value", "")).strip()
            if not tag_value or (tag_type, tag_value) in seen:
                continue
            seen.add((tag_type, tag_value))
            conn.execute(
                """
                INSERT INTO candidate_tags (
                    resume_identity, tag_type, tag_value, confidence, evidence_json, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_identity,
                    tag_type,
                    tag_value,
                    float(row.get("confidence", 0.0) or 0.0),
                    json.dumps(row.get("evidence", {}) or {}, ensure_ascii=False),
                    str(row.get("source", "")).strip(),
                ),
            )

    def _insert_candidate_profile_tags(self, conn: sqlite3.Connection, resume_identity: str, candidate_profile: Dict[str, Any]) -> None:
        rows: List[Dict[str, Any]] = []
        skills = dict(candidate_profile.get("resume_level_skills", {}) or {})
        for item in list(skills.get("normalized", []) or []):
            if isinstance(item, dict):
                rows.append({"tag_type": "skill", **item})
            else:
                rows.append({"tag_type": "skill", "value": item, "confidence": 0.82, "evidence": {}, "source": "rule_merge"})
        for item in list(skills.get("raw", []) or []):
            rows.append({"tag_type": "raw_skill", "value": item, "confidence": 0.72, "evidence": {}, "source": "rule_merge"})
        for field_name, tag_type in (
            ("languages", "language"),
            ("certifications_or_scores", "certification"),
            ("portfolio_links", "portfolio_link"),
        ):
            for item in list(candidate_profile.get(field_name, []) or []):
                if isinstance(item, dict):
                    rows.append({"tag_type": tag_type, **item})
                else:
                    rows.append({"tag_type": tag_type, "value": item, "confidence": 0.72, "evidence": {}, "source": "rule_merge"})
        seen = {
            (str(row[0]).strip(), str(row[1]).strip())
            for row in conn.execute(
                "SELECT tag_type, tag_value FROM candidate_tags WHERE resume_identity = ?",
                (resume_identity,),
            ).fetchall()
        }
        for row in rows:
            tag_type = str(row.get("tag_type", "")).strip()
            tag_value = str(row.get("value", "")).strip()
            if not tag_type or not tag_value or (tag_type, tag_value) in seen:
                continue
            seen.add((tag_type, tag_value))
            conn.execute(
                """
                INSERT INTO candidate_tags (
                    resume_identity, tag_type, tag_value, confidence, evidence_json, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_identity,
                    tag_type,
                    tag_value,
                    float(row.get("confidence", 0.0) or 0.0),
                    json.dumps(row.get("evidence", {}) or {}, ensure_ascii=False),
                    str(row.get("source", "")).strip(),
                ),
            )

    def _insert_projects(
        self,
        conn: sqlite3.Connection,
        resume_identity: str,
        projects: List[Dict[str, Any]],
        project_chunks: List[Dict[str, Any]],
    ) -> None:
        if projects:
            for index, row in enumerate(_dedupe_project_rows(projects, is_chunk=False), start=1):
                project_id = f"project_{index}"
                evidence = {"block_ids": list(row.get("evidence_block_ids", []) or []), "text_snippets": [], "page_refs": []}
                conn.execute(
                    """
                    INSERT INTO project_manifest (
                        resume_identity, project_id, project_name_raw, project_source_type,
                        parent_work_experience_ref, organization_raw, date_range_raw,
                        role_raw, role_normalized, confidence, evidence_json, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resume_identity,
                        project_id,
                        str(row.get("project_name_raw", "")).strip(),
                        str(row.get("project_source_type", "")).strip(),
                        str(row.get("parent_work_experience_ref", "")).strip(),
                        str(row.get("organization_raw", "")).strip(),
                        str(row.get("project_date_range_raw", "")).strip(),
                        str(row.get("role_raw", "")).strip(),
                        str(row.get("role_normalized", "")).strip(),
                        0.86,
                        json.dumps(evidence, ensure_ascii=False),
                        "llm_check",
                    ),
                )
                self._insert_project_tags(conn, resume_identity, project_id, row, evidence)
            return
        seen_project_ids: Dict[str, int] = {}
        for index, row in enumerate(_dedupe_project_rows(project_chunks, is_chunk=True), start=1):
            project_id = _unique_project_id(str(row.get("project_id", "") or row.get("chunk_id", "")).strip(), seen_project_ids, f"project_{index}")
            conn.execute(
                """
                INSERT INTO project_manifest (
                    resume_identity, project_id, project_name_raw, project_source_type,
                    parent_work_experience_ref, organization_raw, date_range_raw,
                    role_raw, role_normalized, confidence, evidence_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_identity,
                    project_id,
                    str(row.get("project_title", "") or row.get("chunk_title", "")).strip(),
                    str(row.get("project_source_type", "") or row.get("candidate_type", "")).strip(),
                    str(row.get("parent_work_experience_ref", "")).strip(),
                    str(row.get("organization_raw", "")).strip(),
                    str(row.get("date_range_raw", "")).strip(),
                    str(row.get("role_raw", "")).strip(),
                    str(row.get("role_normalized", "")).strip(),
                    float(row.get("confidence", 0.0) or 0.0),
                    json.dumps(row.get("evidence", {}) or {}, ensure_ascii=False),
                    str(row.get("source", "")).strip(),
                ),
            )
            self._insert_project_tag_rows(conn, resume_identity, project_id, list(row.get("project_tags", []) or []), "project_tag")

    def _insert_project_tags(
        self,
        conn: sqlite3.Connection,
        resume_identity: str,
        project_id: str,
        row: Dict[str, Any],
        evidence: Dict[str, Any],
    ) -> None:
        tag_rows: List[Dict[str, Any]] = []
        for value in list(row.get("skill_normalized", []) or []):
            tag_rows.append({"tag_type": "skill", "tag_value": str(value).strip(), "raw_value": ""})
        for value in list(row.get("domain_tags", []) or []):
            tag_rows.append({"tag_type": "domain", "tag_value": str(value).strip(), "raw_value": ""})
        if str(row.get("role_normalized", "")).strip():
            tag_rows.append({"tag_type": "role", "tag_value": str(row.get("role_normalized", "")).strip(), "raw_value": str(row.get("role_raw", "")).strip()})
        for value in list(row.get("skill_raw", []) or []):
            tag_rows.append({"tag_type": "raw_skill", "tag_value": str(value).strip(), "raw_value": str(value).strip()})
        self._insert_project_tag_rows(conn, resume_identity, project_id, tag_rows, "llm_check", evidence=evidence)

    def _insert_project_tag_rows(
        self,
        conn: sqlite3.Connection,
        resume_identity: str,
        project_id: str,
        rows: List[Dict[str, Any]],
        source: str,
        evidence: Dict[str, Any] | None = None,
    ) -> None:
        seen = set()
        for row in rows:
            if isinstance(row, dict):
                tag_type = str(row.get("tag_type", "") or "project_tag").strip()
                tag_value = str(row.get("tag_value", "") or row.get("value", "")).strip()
                raw_value = str(row.get("raw_value", "")).strip()
                confidence = float(row.get("confidence", 0.86) or 0.86)
                row_evidence = dict(row.get("evidence", {}) or evidence or {})
                row_source = str(row.get("source", "") or source).strip()
            else:
                tag_type = "project_tag"
                tag_value = str(row).strip()
                raw_value = tag_value
                confidence = 0.86
                row_evidence = dict(evidence or {})
                row_source = source
            if not tag_value or (tag_type, tag_value) in seen:
                continue
            seen.add((tag_type, tag_value))
            conn.execute(
                """
                INSERT INTO project_tags (
                    resume_identity, project_id, tag_type, tag_value, raw_value,
                    confidence, evidence_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_identity,
                    project_id,
                    tag_type,
                    tag_value,
                    raw_value,
                    confidence,
                    json.dumps(row_evidence, ensure_ascii=False),
                    row_source,
                ),
            )


def _unique_project_id(base: str, seen: Dict[str, int], fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(base or "").strip()).strip("_")
    cleaned = cleaned[:120] or fallback
    count = seen.get(cleaned, 0)
    seen[cleaned] = count + 1
    if count <= 0:
        return cleaned
    return f"{cleaned}_{count + 1}"


def _dedupe_project_rows(rows: List[Dict[str, Any]], *, is_chunk: bool) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for row in rows:
        evidence = dict(row.get("evidence", {}) or {})
        key = (
            _normalize_project_key(str(row.get("project_title", "") or row.get("chunk_title", "") or row.get("project_name_raw", ""))),
            _normalize_project_key(str(row.get("organization_raw", ""))),
            _normalize_project_key(str(row.get("date_range_raw", "") or row.get("project_date_range_raw", ""))),
            _normalize_project_key(str(row.get("role_raw", "") or row.get("role_normalized", ""))),
            tuple(sorted(str(item).strip() for item in list((evidence.get("block_ids", []) if is_chunk else row.get("evidence_block_ids", [])) or []) if str(item).strip())),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _normalize_project_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()
