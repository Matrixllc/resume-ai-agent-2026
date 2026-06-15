from __future__ import annotations

from typing import Any, Dict


def _result_shape(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return type(value).__name__
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "none"
    return type(value).__name__


def _result_count(value: Any) -> int | None:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return None


def _compact_value(value: Any, *, max_items: int = 5) -> Any:
    if hasattr(value, "model_dump"):
        return _compact_value(value.model_dump(), max_items=max_items)
    if isinstance(value, dict):
        output: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                output["__truncated__"] = f"+{len(value) - max_items}"
                break
            output[str(key)] = _compact_value(item, max_items=max_items)
        return output
    if isinstance(value, list):
        output = [_compact_value(item, max_items=max_items) for item in value[:max_items]]
        if len(value) > max_items:
            output.append({"__truncated__": f"+{len(value) - max_items}"})
        return output
    if isinstance(value, tuple):
        return _compact_value(list(value), max_items=max_items)
    text = str(value)
    return text[:300] + "..." if len(text) > 300 else value


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _strip_empty(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}
