from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List


def invoke_llm_text(config: Dict[str, Any], prompt: str) -> str:
    errors: List[str] = []
    for attempt in range(1, 4):
        try:
            llm = _build_llm(config)
            response = llm.invoke(prompt)
            return _normalize_content(getattr(response, "content", response))
        except Exception as error:
            errors.append(f"attempt_{attempt}:{type(error).__name__}: {error}")
            if attempt < 3:
                time.sleep(1.2 * attempt)
                continue
    raise RuntimeError(" | ".join(errors))


def extract_json_object(text: str) -> Dict[str, Any]:
    candidates: List[str] = []
    candidates.extend(re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL))
    candidates.extend(re.findall(r"```\s*(\{.*?\})\s*```", text, flags=re.DOTALL))
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("LLM did not return a parseable JSON object.")


def _build_llm(config: Dict[str, Any]) -> Any:
    perf = config.get("performance", {})
    if config["model"].get("chat_provider") == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ModuleNotFoundError as error:
            raise RuntimeError("langchain_openai is required when RESUME_V3_CHAT_PROVIDER=openai") from error
        return ChatOpenAI(
            model=config["model"]["openai_model"],
            api_key=config["env"]["openai_api_key"],
            base_url=config["env"].get("openai_base_url"),
            temperature=float(perf.get("llm_temperature", 0.0)),
            timeout=float(config["env"].get("openai_timeout", 120.0)),
        )
    try:
        from langchain_ollama import ChatOllama
    except ModuleNotFoundError as error:
        raise RuntimeError("langchain_ollama is required when RESUME_V3_CHAT_PROVIDER=ollama") from error
    return ChatOllama(
        model=config["model"]["llm_model"],
        base_url=config["env"]["ollama_host"],
        request_timeout=float(config["env"].get("ollama_timeout", 120.0)),
        temperature=float(perf.get("llm_temperature", 0.0)),
        num_predict=int(perf.get("llm_num_predict", 1200)),
    )


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()
    return str(content).strip()
