from __future__ import annotations

from .config import get_data_access_config
from .sql_reader import ResumeSqlReader


def list_known_candidate_names() -> list[str]:
    """返回供路由规则匹配使用的候选人姓名，且不调用工具层。"""
    try:
        config = get_data_access_config()
        reader = ResumeSqlReader(config["paths"]["structured_store_file"])
        names = [str(row.get("name", "") or "").strip() for row in reader.list_candidates()]
        return [name for name in names if name]
    except Exception:
        # 候选人姓名索引只是 router 的规则增强；不可读时退化为无姓名提示，不阻断主链路。
        return []
