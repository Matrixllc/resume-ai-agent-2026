"""QA-owned LLM client and prompt contracts.

这里暴露 structured LLM 调用入口。LLM 输出只是 draft，仍需 node guard/finalizer/validator 收口。
"""

from .client import ResumeQALLMError, build_chat_model, invoke_structured, is_llm_enabled, llm_identity

__all__ = [
    "ResumeQALLMError",
    "build_chat_model",
    "invoke_structured",
    "is_llm_enabled",
    "llm_identity",
]
