"""QA-owned LLM client public API.

client 子包负责 provider setup、structured invoke 和 payload cleanup，不承载业务规则。
"""

from .errors import ResumeQALLMError
from .models import build_chat_model, is_llm_enabled, llm_identity
from .structured import invoke_structured

__all__ = [
    "ResumeQALLMError",
    "build_chat_model",
    "invoke_structured",
    "is_llm_enabled",
    "llm_identity",
]
