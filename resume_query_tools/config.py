from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


def get_tools_config() -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    v3_root = repo_root / "resume_query_v3"
    return {
        "paths": {
            "repo_root": repo_root,
            "v3_root": v3_root,
            "structured_store_file": Path(os.getenv("RESUME_TOOLS_SQLITE", v3_root / "data" / "structured" / "structured_store.db")),
            "chroma_dir": Path(os.getenv("RESUME_TOOLS_CHROMA_DIR", v3_root / "data" / "vector" / "chroma_store")),
        },
        "storage": {
            "chroma_collection": os.getenv("RESUME_TOOLS_CHROMA_COLLECTION", "resume_v3_project_chunks").strip(),
        },
    }
