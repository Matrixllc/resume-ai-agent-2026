"""Compatibility facade for the Aggregator node.

这个文件负责什么：
  保留历史导入路径，把 graph 需要的 aggregator 入口转发到 core.answer_generation。

应该从哪里继续读：
  真实逻辑在 resume_query_ai_qa.core.answer_generation.generation。

不会负责什么：
  不生成答案、不调用 LLM、不处理 grounding，只做稳定导出。
"""

from resume_query_ai_qa.core.answer_generation import (
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
