"""Shared answer generation public API.

aggregator、answer_rewrite 和 rule fallback 从这里进入答案生成核心。
事实仍以 ToolResult grounded context 为准，LLM 输出必须被收口。
"""

from .generation import (
    aggregate_answer,
    aggregate_answer_llm,
    aggregate_answer_with_meta,
    generate_rewrite_candidate_with_meta,
    render_hard_fallback,
    rewrite_answer_llm,
    rewrite_answer_with_meta,
)

__all__ = [
    "aggregate_answer",
    "aggregate_answer_llm",
    "aggregate_answer_with_meta",
    "generate_rewrite_candidate_with_meta",
    "render_hard_fallback",
    "rewrite_answer_llm",
    "rewrite_answer_with_meta",
]
