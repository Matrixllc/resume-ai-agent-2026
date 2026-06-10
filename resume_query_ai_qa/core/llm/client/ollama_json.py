"""Ollama JSON mode fallback for local structured output.

Some local Ollama models reject complex tool/JSON-schema payloads. JSON mode is
only a transport fallback: the QA package still validates the response with the
same Pydantic schema before downstream nodes see it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Type, TypeVar
from urllib import request

from pydantic import BaseModel

from resume_query_ai_qa.core.config import ResumeQAConfig

from .errors import ResumeQALLMError
from .payload_normalization import normalize_schema_payload
from .schema_contracts import compact_json_contract
from .settings import llm_value


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def invoke_ollama_json_mode(schema: Type[SchemaT], prompt: str, config: ResumeQAConfig) -> SchemaT:
    """获取invokeollamaJSON模式并返回。"""
    base_url = str(llm_value(config, "ollama_base_url", "http://localhost:11434") or "http://localhost:11434").rstrip("/")
    timeout = float(llm_value(config, "ollama_json_timeout", 45) or 45)
    payload = {
        "model": llm_value(config, "ollama_model", "llama3:latest"),
        "prompt": json_mode_prompt(schema, prompt),
        "format": "json",
        "stream": False,
        "options": {
            "temperature": float(llm_value(config, "temperature", 0.0) or 0.0),
            "num_predict": int(llm_value(config, "num_predict", 512) or 512),
        },
    }
    req = request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    parsed = normalize_schema_payload(schema, parse_json_object(response_payload.get("response", "")))
    return schema.model_validate(parsed)


def json_mode_prompt(schema: Type[BaseModel], prompt: str) -> str:
    """获取JSON模式提示词并返回。"""
    contract = compact_json_contract(schema)
    return (
        f"{prompt}\n\n"
        "Return only one valid JSON object. Do not include markdown fences or commentary.\n"
        "Use this compact JSON contract:\n"
        f"{contract}"
    )


def parse_json_object(content: Any) -> dict[str, Any]:
    """解析JSON对象并返回。"""
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ResumeQALLMError("Ollama JSON mode returned a non-object JSON value")
    return parsed


def is_ollama_schema_error(error: Exception) -> bool:
    """判断ollamaschema错误是否成立并返回布尔值。"""
    message = f"{type(error).__name__}: {error}".lower()
    return (
        "invalid json schema" in message
        or "does not support tools" in message
        or "format" in message and "status code: 500" in message
    )
