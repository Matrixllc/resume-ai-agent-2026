"""Structured LLM invocation for Query-AI.

LLM output is never a fact source in this project. It is only a structured
draft that must pass Pydantic validation here and downstream compiler,
validator, or answer checks before it can affect a final response.
"""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config

from .models import build_chat_model, llm_identity
from .ollama_json import invoke_ollama_json_mode, is_ollama_schema_error
from .payload_normalization import normalize_schema_payload


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def invoke_structured(
    schema: Type[SchemaT],
    prompt: str,
    *,
    config: ResumeQAConfig | None = None,
) -> SchemaT:
    """获取invoke结构化并返回。"""
    cfg = config or load_config()
    provider = llm_identity(cfg)["provider"]
    if provider == "ollama":
        return invoke_ollama_json_mode(schema, prompt, cfg)
    method = "json_schema" if provider == "ollama" else "function_calling"
    model = build_chat_model(cfg)
    structured = model.with_structured_output(schema, method=method)
    try:
        result = structured.invoke(prompt)
    except Exception as error:
        if provider != "ollama" or not is_ollama_schema_error(error):
            raise
        return invoke_ollama_json_mode(schema, prompt, cfg)
    if isinstance(result, schema):
        return result
    if isinstance(result, dict):
        result = normalize_schema_payload(schema, result)
    return schema.model_validate(result)
