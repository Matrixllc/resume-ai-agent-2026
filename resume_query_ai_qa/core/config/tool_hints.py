"""tool_policy preferred hints 的归一化 helper。"""

from __future__ import annotations

from typing import Any


def normalize_tool_hints(value: Any) -> list[dict[str, Any]]:
    """把 YAML 中字符串或对象形式的工具 hint 统一成稳定 dict，不决定工具可用性。"""
    hints: list[dict[str, Any]] = []
    for item in list(value or []):
        if isinstance(item, str):
            hints.append({"name": item, "confidence": 0.75})
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        if name:
            hints.append({"name": name, "confidence": float(item.get("confidence", 0.75) or 0.75)})
    return hints
