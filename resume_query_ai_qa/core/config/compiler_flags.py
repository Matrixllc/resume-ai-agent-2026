"""Compiler env flag parsing.

这个文件负责什么：
  从项目 .env / 环境变量读取 workflow template 开关，并推导 compiler 模式。

应该从哪个函数读起：
  compiler_flags_for_config() -> load_project_env() -> env_bool()。

不会负责什么：
  不编译 QueryPlan，不选择 workflow，不修改 YAML。
"""

from __future__ import annotations

import os
from typing import Any

from resume_query_common.env import load_repo_env


class CompilerConfigError(RuntimeError):
    """保留给外部兼容；当前单开关配置不会产生非法组合。"""


def compiler_flags_for_config(config: Any) -> dict[str, Any]:
    """读取单一 workflow env 开关并返回标准化 mode/feature flags。"""
    load_project_env(config)
    workflow_enabled = env_bool("RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED", False)
    generic_enabled = True
    mode = "hybrid_template_binding" if workflow_enabled else "generic_tool_binding"
    return {
        "mode": mode,
        "workflow_template_enabled": workflow_enabled,
        "generic_tool_binding_enabled": generic_enabled,
    }


def load_project_env(config: Any) -> None:
    """从项目根目录加载 .env；只补充环境，不覆盖外部运行时注入。"""
    load_repo_env(override=False)


def env_bool(name: str, default: bool) -> bool:
    """按统一规则解析布尔 env，非法值回到默认值而不在节点里分散处理。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default
