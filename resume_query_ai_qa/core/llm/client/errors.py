"""Errors raised by the QA-owned LLM client."""


class ResumeQALLMError(RuntimeError):
    """Raised when the QA-owned LLM layer cannot produce usable output."""
