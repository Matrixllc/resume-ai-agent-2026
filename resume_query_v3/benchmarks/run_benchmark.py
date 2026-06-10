from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.pipeline import run_ingestion_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run resume_query_v3 benchmark cases.")
    parser.add_argument("--files", nargs="*", default=[], help="Explicit case files.")
    args = parser.parse_args()
    config = get_config()
    cases = [Path(item).expanduser().resolve() for item in args.files] if args.files else sorted(
        path for path in Path(config["paths"]["benchmark_cases_dir"]).glob("*") if path.is_file()
    )
    expected = _load_expected(Path(config["paths"]["benchmark_expected_file"]))
    results: List[Dict[str, Any]] = []
    for case_path in cases:
        result = run_ingestion_pipeline(file_path=case_path, config=config)
        assessment = _assess_case(case_path, result, expected.get(case_path.name, {}))
        results.append(assessment)
    report = {
        "total_cases": len(results),
        "passed_cases": sum(1 for item in results if item["passed"]),
        "results": results,
    }
    report_path = Path(config["paths"]["benchmark_reports_dir"]) / "last_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _load_expected(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _assess_case(case_path: Path, result: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    if "document_profile" in expected:
        checks.append(
            {
                "name": "document_profile",
                "passed": result["document_profile"]["value"] == expected["document_profile"],
                "actual": result["document_profile"]["value"],
                "expected": expected["document_profile"],
            }
        )
    if "min_work_count" in expected:
        actual = len(result.get("work_experiences", []) or [])
        checks.append({"name": "min_work_count", "passed": actual >= expected["min_work_count"], "actual": actual, "expected": expected["min_work_count"]})
    if "min_chunk_count" in expected:
        actual = len(result.get("project_chunks", []) or [])
        checks.append({"name": "min_chunk_count", "passed": actual >= expected["min_chunk_count"], "actual": actual, "expected": expected["min_chunk_count"]})
    if "project_count" in expected:
        actual = int(result.get("project_count", len(result.get("project_chunks", []) or [])) or 0)
        checks.append({"name": "project_count", "passed": actual == expected["project_count"], "actual": actual, "expected": expected["project_count"]})
    if "min_project_count" in expected:
        actual = int(result.get("project_count", len(result.get("project_chunks", []) or [])) or 0)
        checks.append({"name": "min_project_count", "passed": actual >= expected["min_project_count"], "actual": actual, "expected": expected["min_project_count"]})
    if "education_count" in expected:
        actual = len(result.get("education_experiences", []) or [])
        checks.append({"name": "education_count", "passed": actual == expected["education_count"], "actual": actual, "expected": expected["education_count"]})
    if "stored_vector_count" in expected:
        actual = len(list(dict(result.get("storage_summary", {}) or {}).get("vector_rows", []) or []))
        checks.append({"name": "stored_vector_count", "passed": actual == expected["stored_vector_count"], "actual": actual, "expected": expected["stored_vector_count"]})
    passed = all(item["passed"] for item in checks) if checks else True
    return {
        "case": case_path.name,
        "passed": passed,
        "resolve_mode": result["run_meta"]["resolve_mode"],
        "document_profile": result["document_profile"]["value"],
        "work_count": len(result.get("work_experiences", []) or []),
        "education_count": len(result.get("education_experiences", []) or []),
        "project_count": int(result.get("project_count", len(result.get("project_chunks", []) or [])) or 0),
        "chunk_count": len(result.get("project_chunks", []) or []),
        "frontend_ready": bool(result["run_meta"]["resolve_mode"] == "llm_success" and result.get("candidate_profile") and result.get("project_chunks")),
        "checks": checks,
    }


if __name__ == "__main__":
    main()
