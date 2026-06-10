from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


class ResumeSqlReader:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def list_candidates(self) -> List[Dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT
                c.*,
                (
                    SELECT COUNT(*)
                    FROM project_manifest p
                    WHERE p.resume_identity = c.resume_identity
                ) AS project_count,
                (
                    SELECT COUNT(*)
                    FROM work_experiences w
                    WHERE w.resume_identity = c.resume_identity
                ) AS work_count
            FROM candidates c
            ORDER BY c.name, c.resume_identity
            """,
            (),
        )

    def get_candidate(self, resume_identity: str) -> Dict[str, Any] | None:
        return self._fetch_one("SELECT * FROM candidates WHERE resume_identity = ?", (resume_identity,))

    def list_work_experiences(self, resume_identity: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM work_experiences WHERE resume_identity = ? ORDER BY id",
            (resume_identity,),
        )

    def list_education_experiences(self, resume_identity: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM education_experiences WHERE resume_identity = ? ORDER BY id",
            (resume_identity,),
        )

    def list_candidate_tags(self, resume_identity: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM candidate_tags WHERE resume_identity = ? ORDER BY tag_type, tag_value",
            (resume_identity,),
        )

    def list_projects(self, resume_identity: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM project_manifest WHERE resume_identity = ? ORDER BY id",
            (resume_identity,),
        )

    def list_project_tags(self, resume_identity: str) -> List[Dict[str, Any]]:
        return self._fetch_all(
            "SELECT * FROM project_tags WHERE resume_identity = ? ORDER BY project_id, tag_type, tag_value",
            (resume_identity,),
        )

    def list_tags_for_candidates(self, resume_identities: List[str] | None = None) -> List[Dict[str, Any]]:
        """Read candidate and project tags in two indexed batch queries."""
        ids = [str(item).strip() for item in (resume_identities or []) if str(item).strip()]
        where = ""
        params: tuple[Any, ...] = ()
        if resume_identities is not None:
            if not ids:
                return []
            placeholders = ", ".join("?" for _item in ids)
            where = f" WHERE resume_identity IN ({placeholders})"
            params = tuple(ids)
        candidate_rows = self._fetch_all(
            f"""
            SELECT resume_identity, tag_type, tag_value, 'candidate_tags' AS tag_source
            FROM candidate_tags
            {where}
            ORDER BY resume_identity, tag_type, tag_value
            """,
            params,
        )
        project_rows = self._fetch_all(
            f"""
            SELECT resume_identity, tag_type, tag_value, 'project_tags' AS tag_source
            FROM project_tags
            {where}
            ORDER BY resume_identity, tag_type, tag_value
            """,
            params,
        )
        return [*candidate_rows, *project_rows]

    def health(self) -> Dict[str, Any]:
        exists = self.db_path.exists()
        if not exists:
            return {"ok": False, "path": str(self.db_path), "candidate_count": 0}
        row = self._fetch_one("SELECT COUNT(*) AS count FROM candidates", ())
        return {"ok": True, "path": str(self.db_path), "candidate_count": int(row.get("count", 0) if row else 0)}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> Dict[str, Any] | None:
        if not self.db_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return _row_to_dict(row) if row else None

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> List[Dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]


def parse_evidence_ids(row: Dict[str, Any]) -> List[str]:
    evidence = _parse_json_object(str(row.get("evidence_json", "{}") or "{}"))
    return [str(item).strip() for item in list(evidence.get("block_ids", []) or []) if str(item).strip()]


def _parse_json_object(value: str) -> Dict[str, Any]:
    try:
        loaded = json.loads(value)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}
