"""Tool hint helpers for generic plan compilation."""

from __future__ import annotations

from resume_query_ai_qa.core.schemas import SemanticStep, ToolHint


def rejected_hint(hint: ToolHint, reason: str, *, intent: str) -> dict[str, object]:
    """获取被拒绝工具建议并返回。"""
    return {"tool": hint.name, "confidence": hint.confidence, "source": hint.source, "intent": intent, "reason": reason}


def scored_tool_hints(step: SemanticStep) -> list[ToolHint]:
    """获取scored工具工具建议集合并返回。"""
    scored = list(step.tool_hint_scores)
    known = {hint.name for hint in scored}
    scored.extend(ToolHint(name=name, confidence=0.5, source="llm") for name in step.tool_hints if name not in known)
    return sorted(scored, key=lambda hint: -hint.confidence)


def dedupe_tool_hints(hints: list[ToolHint]) -> list[ToolHint]:
    """去重工具工具建议集合并返回。"""
    output: list[ToolHint] = []
    seen: set[str] = set()
    for hint in hints:
        if hint.name not in seen:
            output.append(hint)
            seen.add(hint.name)
    return output
