"""compiler env 开关解析与一致性校验。"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv


class CompilerConfigError(RuntimeError):
    """compiler 模式配置错误；启动期抛出，避免 compiler 节点自行兜底猜测。"""


def compiler_flags_for_config(config: Any) -> dict[str, Any]:
    """根据配置生成compiler标记集合并返回。"""
    load_project_env(config)
    workflow_enabled = env_bool("RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED", True)
    generic_enabled = env_bool("RESUME_QA_GENERIC_TOOL_COMPILER_ENABLED", False)
    mode = os.getenv("RESUME_QA_COMPILER_MODE", "").strip().lower()
    if not workflow_enabled and not generic_enabled:
        raise CompilerConfigError(
            "At least one compiler must be enabled: "
            "RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED or RESUME_QA_GENERIC_TOOL_COMPILER_ENABLED"
        )
    if not mode:
        mode = "hybrid_template_binding" if workflow_enabled and generic_enabled else ("workflow_template" if workflow_enabled else "generic_tool_binding")
    if mode not in {"workflow_template", "generic_tool_binding", "hybrid_template_binding"}:
        raise CompilerConfigError(f"unsupported RESUME_QA_COMPILER_MODE: {mode}")
    if mode == "workflow_template" and not workflow_enabled:
        raise CompilerConfigError("RESUME_QA_COMPILER_MODE=workflow_template but workflow compiler is disabled")
    if mode == "generic_tool_binding" and not generic_enabled:
        raise CompilerConfigError("RESUME_QA_COMPILER_MODE=generic_tool_binding but generic compiler is disabled")
    if mode == "hybrid_template_binding" and not (workflow_enabled and generic_enabled):
        raise CompilerConfigError(
            "RESUME_QA_COMPILER_MODE=hybrid_template_binding requires both workflow and generic compilers enabled"
        )
    return {
        "mode": mode,
        "workflow_template_enabled": workflow_enabled,
        "generic_tool_binding_enabled": generic_enabled,
    }


def load_project_env(config: Any) -> None:
    """从项目根目录加载 .env；只补充环境，不覆盖外部运行时注入。"""
    project_root = config.app_root.parent
    load_dotenv(project_root / ".env", override=False)


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
