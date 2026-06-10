"""配置校验共享 helper。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def check_tool(prefix: str, field: str, tool: Any, tools: set[str], errors: list[str]) -> None:
    """校验配置字段引用的工具名存在且非空。"""
    value = str(tool or "").strip()
    if not value:
        errors.append(f"{prefix}.{field} contains an empty tool name")
    elif value not in tools:
        errors.append(f"{prefix}.{field} references unknown tool `{value}`")


def yaml_mapping(path: Path, errors: list[str]) -> dict[str, Any]:
    """读取 YAML 并确保顶层是 mapping，用于 taxonomy 文件结构校验。"""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as error:
        errors.append(f"shared_taxonomy: cannot read `{path}`: {error}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"shared_taxonomy: `{path}` must contain a mapping")
        return {}
    return payload
