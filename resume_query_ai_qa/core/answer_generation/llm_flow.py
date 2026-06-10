"""答案生成中的 LLM fill/rewrite 受控流程。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.core.schemas import AggregatedAnswer

from .layout import validate_layout_contract
from .llm import (
    build_fill_prompt,
    build_rewrite_prompt,
    fill_answer_with_llm,
    merge_grounding,
    reject_if_fact_drifted,
    rewrite_answer_with_llm,
)
from .orchestration import AnswerInputs, dedupe_warnings


@dataclass(frozen=True)
class LLMFlowResult:
    """LLM 流程结果；answer 可为空，调用方决定是否回落规则答案。"""

    answer: AggregatedAnswer | None
    engine: str
    fallback_reason: str
    drift_reason: str
    mode: str
    llm_response: AggregatedAnswer
    prompt: str


def run_fill_flow(inputs: AnswerInputs, grounded: AggregatedAnswer, config: ResumeQAConfig, *, use_llm: bool) -> LLMFlowResult:
    """执行 aggregator 的 LLM fill；失败或漂移时回到 grounded 规则答案。"""
    answer = grounded
    engine = "rule"
    fallback_reason = ""
    drift_reason = ""
    mode = "rule_grounded_renderer"
    llm_response = grounded
    prompt = ""
    if use_llm and is_llm_enabled(config):
        prompt = build_fill_prompt(inputs.payload)
        try:
            generated = fill_answer_with_llm(inputs.payload, config)
            llm_response = generated
            drift_reason, layout_violation, rejection_reason = _rejection_reason(generated, inputs)
            if rejection_reason:
                fallback_reason = rejection_reason
                mode = "llm_fill_rejected"
                answer = grounded.model_copy(update={"warnings": dedupe_warnings([*grounded.warnings, f"llm_fill_rejected:{rejection_reason}"])})
            else:
                answer = merge_grounding(generated, grounded)
                engine = "llm"
                mode = "llm_fill"
        except Exception as error:
            fallback_reason = short_error(error)
            mode = "rule_fallback_after_llm_error"
            answer = grounded.model_copy(update={"warnings": dedupe_warnings([*grounded.warnings, f"llm_fill_error:{fallback_reason}"])})
    return LLMFlowResult(answer, engine, fallback_reason, drift_reason, mode, llm_response, prompt)


def run_rewrite_flow(
    inputs: AnswerInputs,
    grounded: AggregatedAnswer,
    previous_answer: AggregatedAnswer,
    answer_errors: list[str],
    config: ResumeQAConfig,
    *,
    use_llm: bool,
) -> LLMFlowResult:
    """执行 answer_rewrite 的 LLM rewrite；候选不可用时返回 None 给 facade 回落。"""
    answer: AggregatedAnswer | None = None
    engine = "llm"
    fallback_reason = ""
    drift_reason = ""
    mode = "llm_rewrite_skipped"
    llm_response = grounded
    prompt = ""
    if use_llm and is_llm_enabled(config):
        prompt = build_rewrite_prompt(inputs.payload, previous_answer, answer_errors)
        try:
            generated = rewrite_answer_with_llm(inputs.payload, previous_answer, answer_errors, config)
            llm_response = generated
            drift_reason, layout_violation, rejection_reason = _rejection_reason(generated, inputs)
            if rejection_reason:
                fallback_reason = rejection_reason
                mode = "llm_rewrite_rejected"
            else:
                answer = merge_grounding(generated, grounded)
                mode = "llm_rewrite"
        except Exception as error:
            fallback_reason = short_error(error)
            mode = "llm_rewrite_error"
    else:
        engine = "rule_fallback_request"
        fallback_reason = "llm_disabled"
    return LLMFlowResult(answer, engine, fallback_reason, drift_reason, mode, llm_response, prompt)


def short_error(error: Exception) -> str:
    """压缩异常信息写入 trace，避免把长堆栈或多行 provider 报错塞进元数据。"""
    message = str(error).strip().replace("\n", " ")
    if len(message) > 220:
        message = message[:220] + "..."
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _rejection_reason(generated: AggregatedAnswer, inputs: AnswerInputs) -> tuple[str, str, str]:
    """统一判断 LLM 输出是否事实漂移或 layout 违约，两条路径共用同一拒绝规则。"""
    drift_reason = reject_if_fact_drifted(generated, inputs.context, inputs.rule_draft)
    layout_violation = validate_layout_contract(generated.answer or "", inputs.rule_draft)
    rejection_reason = f"fact_drift:{drift_reason}" if drift_reason else (f"layout_contract:{layout_violation}" if layout_violation else "")
    return drift_reason, layout_violation, rejection_reason
