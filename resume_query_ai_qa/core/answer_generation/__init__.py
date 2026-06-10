"""Shared answer generation API."""

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
