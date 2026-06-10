"""Provider-specific model construction for the QA LLM layer."""

from __future__ import annotations

import os
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.config.compiler_flags import load_project_env

from .errors import ResumeQALLMError
from .settings import configured_provider, llm_value, provider_disabled


def is_llm_enabled(config: ResumeQAConfig | None = None) -> bool:
    """判断大模型启用状态是否成立并返回布尔值。"""
    return not provider_disabled(configured_provider(config))


def build_chat_model(config: ResumeQAConfig | None = None) -> Any:
    """构建问答模块自有的 LangChain 对话模型。

    本模块封装在 ``resume_query_ai_qa`` 内，不导入或复用 v3 的大模型客户端、配置或提示词。
    """
    cfg = config or load_config()
    load_project_env(cfg)
    provider = configured_provider(cfg)
    temperature = float(llm_value(cfg, "temperature", 0.0) or 0.0)
    timeout = float(llm_value(cfg, "timeout", 120) or 120)
    max_retries = int(llm_value(cfg, "max_retries", 2) or 0)

    if provider_disabled(provider):
        raise ResumeQALLMError("QA LLM provider is disabled")
    if provider == "openai":
        return _build_openai_model(cfg, temperature, timeout, max_retries)
    if provider == "ollama":
        return _build_ollama_model(cfg, temperature, timeout)
    raise ResumeQALLMError(f"unsupported QA LLM provider: {provider}")


def llm_identity(config: ResumeQAConfig | None = None) -> dict[str, str]:
    """返回已配置的问答大模型提供方与模型名，不暴露敏感信息。"""
    cfg = config or load_config()
    load_project_env(cfg)
    provider = configured_provider(cfg)
    model = ""
    base_url = ""
    if provider == "openai":
        model = str(llm_value(cfg, "openai_model", "gpt-4.1-mini") or "")
        base_url = str(llm_value(cfg, "openai_base_url", "https://api.openai.com/v1") or "")
    elif provider == "ollama":
        model = str(llm_value(cfg, "ollama_model", "llama3:latest") or "")
        base_url = str(llm_value(cfg, "ollama_base_url", "http://localhost:11434") or "")
    return {"provider": provider or "disabled", "model": model, "base_url": base_url}


def _build_openai_model(config: ResumeQAConfig, temperature: float, timeout: float, max_retries: int) -> Any:
    """构建openai模型并返回。"""
    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as error:
        raise ResumeQALLMError("langchain_openai is required for provider=openai") from error
    api_key = os.getenv("RESUME_QA_OPENAI_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ResumeQALLMError("RESUME_QA_OPENAI_API_KEY or OPENAI_API_KEY is required for provider=openai")
    return ChatOpenAI(
        model=llm_value(config, "openai_model", "gpt-4.1-mini"),
        api_key=api_key,
        base_url=llm_value(config, "openai_base_url", "https://api.openai.com/v1"),
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
    )


def _build_ollama_model(config: ResumeQAConfig, temperature: float, timeout: float) -> Any:
    """构建ollama模型并返回。"""
    try:
        from langchain_ollama import ChatOllama
    except ModuleNotFoundError as error:
        raise ResumeQALLMError("langchain_ollama is required for provider=ollama") from error
    return ChatOllama(
        model=llm_value(config, "ollama_model", "llama3:latest"),
        base_url=llm_value(config, "ollama_base_url", "http://localhost:11434"),
        temperature=temperature,
        request_timeout=timeout,
        num_predict=int(llm_value(config, "num_predict", 1200) or 1200),
    )
