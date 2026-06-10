"""Router pipeline entrypoint.

Read this file first. It only wires the five router stages and deliberately
keeps business rules in the sibling modules:

preprocess_router_question -> build_router_draft -> apply_router_guards ->
complete_router_conditions -> finalize_router_output.

This module does not inspect YAML rules directly, classify intent details, or
build tool plans. It turns a user question into the final RouterOutput by
delegating each stage to the focused module that owns it.
"""

from __future__ import annotations

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.core.schemas import RouterOutput

from . import rules
from .conditions import complete_router_conditions, preprocess_router_question
from .finalizer import finalize_router_output, safe_out_of_scope
from .guard import apply_router_guards
from .llm import build_llm_router_draft


def route_question(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """Rule-only router entrypoint.

    Reads YAML through ResumeQAConfig and always uses the deterministic rule
    draft. Later stages are identical to the LLM entrypoint.
    """
    return run_router_pipeline(question, config or load_config(), use_llm=False)


def route_question_llm(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """LLM-first router entrypoint.

    The LLM should produce a complete RouterOutput draft. If LLM is disabled or
    the draft fails validation inside llm.py, the pipeline uses rule fallback.
    """
    return run_router_pipeline(question, config or load_config(), use_llm=True)


def run_router_pipeline(question: str, config: ResumeQAConfig, *, use_llm: bool) -> RouterOutput:
    """Run the five router stages from raw question to final RouterOutput.

    Stage ownership:
    1. conditions.py cleans the question.
    2. llm.py or rules.py builds a RouterOutput draft.
    3. guard.py applies hard rule corrections.
    4. conditions.py completes missing QueryCondition items.
    5. finalizer.py recomputes authoritative derived fields.
    """
    cleaned_question = preprocess_router_question(question, config)
    draft = build_router_draft(cleaned_question, config, use_llm=use_llm)
    guarded = apply_router_guards(draft, cleaned_question, config)
    completed = complete_router_conditions(guarded, cleaned_question, config)
    return safe_finalize_router_output(completed, cleaned_question, config)


def build_router_draft(question: str, config: ResumeQAConfig, *, use_llm: bool) -> RouterOutput:
    """Build the RouterOutput draft before guard and finalizer stages.

    Empty questions are immediately drafted as out_of_scope. LLM mode is only
    used when the runtime config enables it; otherwise the deterministic rule
    fallback produces the full draft.
    """
    if not question:
        return rules.build_out_of_scope_draft(question, config)
    if use_llm and is_llm_enabled(config):
        return build_llm_router_draft(question, config)
    return rules.build_rule_router_draft(question, config)


def safe_finalize_router_output(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Finalize RouterOutput, safely degrading to out_of_scope on finalizer errors."""
    try:
        return finalize_router_output(output, question, config)
    except Exception as error:
        return safe_out_of_scope(question, config, f"{type(error).__name__}: {str(error)[:120]}")
