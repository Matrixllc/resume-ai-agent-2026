"""QA-owned LLM client and prompt contracts."""

from .client import ResumeQALLMError, build_chat_model, invoke_structured, is_llm_enabled, llm_identity

__all__ = [
    "ResumeQALLMError",
    "build_chat_model",
    "invoke_structured",
    "is_llm_enabled",
    "llm_identity",
]
