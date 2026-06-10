from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.pipeline import run_ingestion_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run resume_query_v3 ingestion on a single file.")
    parser.add_argument("--file", required=True, help="Path to resume file.")
    parser.add_argument("--print-json", action="store_true", help="Print final JSON result.")
    parser.add_argument("--verbose-third-party", action="store_true", help="Show Docling/RapidOCR/Ollama/OpenAI low-level logs.")
    args = parser.parse_args()
    file_path = Path(args.file).expanduser().resolve()
    config = get_config()
    if args.verbose_third_party:
        config.setdefault("logging", {})["verbose_third_party"] = True
    _configure_logging(verbose=bool(config.get("logging", {}).get("verbose_third_party", False)))
    _flow(f"start file={file_path.name}")
    result = run_ingestion_pipeline(file_path=file_path, config=config, progress_callback=_flow)
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(_summary_payload(result), ensure_ascii=False, indent=2))
    _flow("done")


def _summary_payload(result: dict) -> dict:
    storage_summary = dict(result.get("storage_summary", {}) or {})
    storage_gate = dict(result.get("storage_gate", {}) or {})
    return {
        "run_id": result["run_meta"]["run_id"],
        "resolve_mode": result["run_meta"]["resolve_mode"],
        "document_profile": result["document_profile"]["value"],
        "name": dict(result.get("candidate_profile", {}).get("name", {}) or {}).get("value", ""),
        "work_count": len(result.get("work_experiences", []) or []),
        "education_count": len(result.get("education_experiences", []) or []),
        "project_count": result.get("project_count", len(result.get("project_chunks", []) or [])),
        "project_candidate_count": len(result.get("project_chunks", []) or []),
        "stored_project_rows": len(list(storage_summary.get("project_manifest_rows", []) or [])),
        "stored_vector_rows": len(list(storage_summary.get("vector_rows", []) or [])),
        "storage_blocked_reason": storage_gate.get("storage_blocked_reason", ""),
        "last_run_log": str(REPO_ROOT / "resume_query_v3" / "logs" / "latest" / "last_run_log.txt"),
    }


def _configure_logging(*, verbose: bool) -> None:
    if verbose:
        return
    logging.basicConfig(level=logging.WARNING)
    for logger_name in (
        "RapidOCR",
        "rapidocr",
        "docling",
        "onnxruntime",
        "httpx",
        "openai",
        "chromadb",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _flow(message: str) -> None:
    print(f"[resume_query_v3] {message}", file=sys.stderr)


if __name__ == "__main__":
    main()
