"""Configuration helpers for the QA-owned LLM client."""

from __future__ import annotations

import os
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.config.compiler_flags import load_project_env


def configured_provider(config: ResumeQAConfig | None = None) -> str:
    """获取配置化提供方并返回。"""
    cfg = config or load_config()
    load_project_env(cfg)
    return str(llm_value(cfg, "provider", "disabled") or "").strip().lower()


def provider_disabled(provider: str) -> bool:
    """获取提供方disabled并返回。"""
    return provider in {"", "disabled", "none", "off", "false"}


def llm_value(config: ResumeQAConfig, key: str, default: Any) -> Any:
    """获取大模型值并返回。"""
    for env_name in env_names(key):
        env_value = os.getenv(env_name)
        if env_value is not None:
            return env_value
    return config.llm.get(key, default)


def env_names(key: str) -> list[str]:
    """获取ENV名称集合并返回。"""
    preferred = {
        "provider": ["RESUME_QA_LLM_PROVIDER"],
        "temperature": ["RESUME_QA_LLM_TEMPERATURE"],
        "timeout": ["RESUME_QA_LLM_TIMEOUT"],
    }
    return preferred.get(key, []) + [f"RESUME_QA_{key.upper()}"]
