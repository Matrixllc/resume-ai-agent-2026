"""Router pipeline entrypoint.

Read this file first. It only wires the five router stages and deliberately
keeps business rules in the sibling modules:

preprocess_router_question -> build_router_draft -> apply_router_guards ->
complete_router_conditions -> finalize_router_output.

This module does not inspect YAML rules directly, classify intent details, or
build tool plans. It turns a user question into the final RouterOutput by
delegating each stage to the focused module that owns it.

中文阅读提示：
这个文件是 router 节点的总入口，只负责把 5 个阶段串起来。
业务判断放在 rules.py / guard.py / finalizer.py 等文件里；这里不要读 YAML
细节，也不要生成工具计划。你读代码时先看 route_question_llm()，再看
run_router_pipeline()，主链路就清楚了。
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

    中文：
    纯规则入口，不走 LLM。它仍然会走完整 5 阶段 pipeline，只是在 draft 阶段
    固定使用 rules.py 生成 RouterOutput 草稿。
    """
    return run_router_pipeline(question, config or load_config(), use_llm=False)


def route_question_llm(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """LLM-first router entrypoint.

    The LLM should produce a complete RouterOutput draft. If LLM is disabled or
    the draft fails validation inside llm.py, the pipeline uses rule fallback.

    中文：
    LLM 优先入口。LLM 负责先给一个完整 RouterOutput 草稿；如果 LLM 没开、
    输出不合法，或者 scenario 合同不合法，就退回 rules.py 的规则草稿。
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

    中文：
    这是 router 最核心的阅读线：清理问题 -> 生成草稿 -> 硬规则纠偏 ->
    补条件 -> 最终权威收口。后面所有复杂函数都服务这条线。
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

    中文：
    这里只决定“草稿从哪里来”：空问题直接 out_of_scope；LLM 可用就先走 LLM；
    否则用规则 fallback。这里不做最终判断。
    """
    if not question:
        return rules.build_out_of_scope_draft(question, config)
    if use_llm and is_llm_enabled(config):
        return build_llm_router_draft(question, config)
    return rules.build_rule_router_draft(question, config)


def safe_finalize_router_output(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Finalize RouterOutput, safely degrading to out_of_scope on finalizer errors.

    中文：
    最后一道保险。如果 finalizer 自己报错，就返回安全的 out_of_scope，
    避免 router 节点把异常继续往后传。
    """
    try:
        return finalize_router_output(output, question, config)
    except Exception as error:
        return safe_out_of_scope(question, config, f"{type(error).__name__}: {str(error)[:120]}")
