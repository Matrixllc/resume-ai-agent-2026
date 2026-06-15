from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_v3.config import get_config
from resume_query_v3.core.data_layer.storage.backends import clear_chroma_system_cache
from resume_query_v3.core.data_layer.storage.job_store import PipelineJobStore
from resume_query_v3.core.data_layer.storage.structured_store import StructuredStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive and reset resume_query_v3 storage and logs.")
    parser.add_argument("--yes", action="store_true", help="Required to perform destructive cleanup after backup.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be archived and reset without deleting anything.")
    args = parser.parse_args()
    if not args.yes and not args.dry_run:
        raise SystemExit("Refusing to reset storage without --yes. Use --dry-run to preview.")
    config = get_config()
    report = reset_storage(config=config, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def reset_storage(*, config: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    paths = config["paths"]
    app_root = Path(paths["app_root"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(paths["data_dir"]) / "backups" / timestamp
    targets = [
        Path(paths["jobs_db"]),
        Path(paths["structured_store_file"]),
        Path(paths["chroma_dir"]),
        Path(paths["vector_payload_file"]),
        Path(paths["logs_latest_dir"]),
        Path(paths["logs_history_dir"]),
    ]
    existing_targets = [path for path in targets if path.exists()]
    report: Dict[str, Any] = {
        "dry_run": dry_run,
        "backup_dir": str(backup_dir),
        "archived": [],
        "removed": [],
        "recreated": [],
        "skipped_missing": [str(path.relative_to(app_root)) for path in targets if not path.exists()],
    }
    if dry_run:
        report["would_archive"] = [str(path.relative_to(app_root)) for path in existing_targets]
        report["would_remove"] = [str(path.relative_to(app_root)) for path in existing_targets]
        return report

    clear_chroma_system_cache()
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in existing_targets:
        relative = path.relative_to(app_root)
        destination = backup_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, destination)
        else:
            shutil.copy2(path, destination)
        report["archived"].append(str(relative))

    for path in existing_targets:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        report["removed"].append(str(path.relative_to(app_root)))

    _recreate_storage(config=config, report=report)
    clear_chroma_system_cache()
    return report


def _recreate_storage(*, config: Dict[str, Any], report: Dict[str, Any]) -> None:
    paths = config["paths"]
    for key in ("logs_latest_dir", "logs_history_dir"):
        path = Path(paths[key])
        path.mkdir(parents=True, exist_ok=True)
        report["recreated"].append(str(path.relative_to(Path(paths["app_root"]))))
    Path(paths["vector_payload_file"]).parent.mkdir(parents=True, exist_ok=True)
    Path(paths["chroma_dir"]).mkdir(parents=True, exist_ok=True)
    StructuredStore(Path(paths["structured_store_file"]))
    PipelineJobStore(Path(paths["jobs_db"]))
    report["recreated"].extend(
        [
            str(Path(paths["structured_store_file"]).relative_to(Path(paths["app_root"]))),
            str(Path(paths["jobs_db"]).relative_to(Path(paths["app_root"]))),
            str(Path(paths["chroma_dir"]).relative_to(Path(paths["app_root"]))),
        ]
    )
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(Path(paths["chroma_dir"])))
        client.get_or_create_collection(name=str(config["storage"].get("chroma_collection", "resume_v3_project_chunks")).strip())
        report["recreated"].append(f"chroma_collection:{config['storage'].get('chroma_collection', 'resume_v3_project_chunks')}")
    except Exception as error:
        report["chroma_recreate_warning"] = f"{type(error).__name__}: {error}"


if __name__ == "__main__":
    main()
