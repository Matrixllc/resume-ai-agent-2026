from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict


class PipelineJobStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    resume_identity TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parser_mode TEXT DEFAULT '',
                    resolve_mode TEXT DEFAULT '',
                    error_message TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                DELETE FROM ingestion_runs
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM ingestion_runs
                    GROUP BY resume_identity
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_runs_resume_identity ON ingestion_runs(resume_identity)")

    def mark_started(self, *, run_id: str, resume_identity: str, source_path: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            existing_resume = conn.execute(
                "SELECT id FROM ingestion_runs WHERE resume_identity = ?",
                (resume_identity,),
            ).fetchone()
            if existing_resume:
                conn.execute(
                    """
                    UPDATE ingestion_runs
                    SET run_id = ?, source_path = ?, status = ?, parser_mode = '', resolve_mode = '', error_message = ''
                    WHERE id = ?
                    """,
                    (run_id, source_path, "RUNNING", existing_resume[0]),
                )
                return

            existing_run = conn.execute(
                "SELECT id FROM ingestion_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing_run:
                conn.execute(
                    """
                    UPDATE ingestion_runs
                    SET resume_identity = ?, source_path = ?, status = ?, parser_mode = '', resolve_mode = '', error_message = ''
                    WHERE id = ?
                    """,
                    (resume_identity, source_path, "RUNNING", existing_run[0]),
                )
                return

            conn.execute(
                """
                INSERT INTO ingestion_runs (run_id, resume_identity, source_path, status)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, resume_identity, source_path, "RUNNING"),
            )

    def mark_finished(self, *, run_id: str, status: str, parser_mode: str, resolve_mode: str, error_message: str = "") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE ingestion_runs
                SET status = ?, parser_mode = ?, resolve_mode = ?, error_message = ?
                WHERE run_id = ?
                """,
                (status, parser_mode, resolve_mode, error_message, run_id),
            )

    def count_runs_for_resume(self, resume_identity: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT CASE WHEN EXISTS(SELECT 1 FROM ingestion_runs WHERE resume_identity = ?) THEN 1 ELSE 0 END",
                (resume_identity,),
            ).fetchone()
        return int(row[0] if row else 0)
