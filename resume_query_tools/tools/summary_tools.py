from __future__ import annotations

import json
from typing import Any, Dict, List

from resume_query_v3.config import get_config as get_v3_config
from resume_query_v3.core.data_layer.llm.llm_client import extract_json_object, invoke_llm_text

from ..schemas import CandidateSummaryResponse, SummarySections
from .candidate_summary_context_tool import build_candidate_summary_context


def generate_candidate_summary(resume_identity: str) -> CandidateSummaryResponse:
    """生成候选人展示摘要。

    它先用 `build_candidate_summary_context()` 收集事实，再调用 v3 配置的 LLM
    做受限总结。LLM 失败时返回规则 fallback。这个接口服务候选人展示页，
    不参与 QA graph 的事实判断。
    """
    context = build_candidate_summary_context(resume_identity)
    config = get_v3_config()
    provider = str(config["model"].get("chat_provider", "") or "")
    model = _model_name(config)
    prompt = _build_summary_prompt(context.summary_inputs)
    try:
        raw_response = invoke_llm_text(config, prompt)
        parsed = extract_json_object(raw_response)
        sections = _sections_from_payload(parsed)
        summary = str(parsed.get("summary", "") or sections.overall_summary).strip()
        return CandidateSummaryResponse(
            resume_identity=resume_identity,
            summary=summary,
            summary_sections=sections,
            summary_inputs=context.summary_inputs,
            provider=provider,
            model=model,
        )
    except Exception as error:
        sections = _fallback_sections(context.summary_inputs)
        return CandidateSummaryResponse(
            resume_identity=resume_identity,
            summary=sections.overall_summary,
            summary_sections=sections,
            summary_inputs=context.summary_inputs,
            provider=provider,
            model=model,
            llm_error=f"{type(error).__name__}: {error}",
        )


def _build_summary_prompt(summary_inputs: Dict[str, Any]) -> str:
    """构造“只根据输入 JSON 总结”的受限 prompt。"""
    payload = json.dumps(summary_inputs, ensure_ascii=False, indent=2)
    return f"""你是一个简历信息总结助手。请只根据输入 JSON 总结，不要编造。

返回一个 JSON 对象，格式严格如下：
{{
  "summary": "",
  "summary_sections": {{
    "overall_summary": "",
    "personal_summary": "",
    "project_summary": "",
    "work_experience_summary": "",
    "strengths": [],
    "risks_or_missing_info": []
  }}
}}

写作要求：
- 使用中文。
- 总结候选人的个人定位、技能、普通项目、工作经历。
- strengths 写 3-6 条。
- risks_or_missing_info 写信息缺口或需要复核的点；没有就返回空数组。
- 不要输出 Markdown。

输入 JSON：
{payload}
"""


def _sections_from_payload(payload: Dict[str, Any]) -> SummarySections:
    raw_sections = dict(payload.get("summary_sections", {}) or {})
    return SummarySections(
        overall_summary=str(raw_sections.get("overall_summary", "") or payload.get("summary", "") or ""),
        personal_summary=str(raw_sections.get("personal_summary", "") or ""),
        project_summary=str(raw_sections.get("project_summary", "") or ""),
        work_experience_summary=str(raw_sections.get("work_experience_summary", "") or ""),
        strengths=_string_list(raw_sections.get("strengths", [])),
        risks_or_missing_info=_string_list(raw_sections.get("risks_or_missing_info", [])),
    )


def _fallback_sections(summary_inputs: Dict[str, Any]) -> SummarySections:
    name = str(summary_inputs.get("name", "") or "该候选人")
    job_intent = str(summary_inputs.get("job_intent", "") or "未标注求职意向")
    skills = _string_list(summary_inputs.get("skills", []))
    projects = list(summary_inputs.get("projects", []) or [])
    work_experiences = list(summary_inputs.get("work_experiences", []) or [])
    project_names = [
        str(dict(item).get("project_name_raw", "") or "").strip()
        for item in projects
        if isinstance(item, dict) and str(dict(item).get("project_name_raw", "") or "").strip()
    ]
    companies = [
        str(dict(item).get("company_name", "") or "").strip()
        for item in work_experiences
        if isinstance(item, dict) and str(dict(item).get("company_name", "") or "").strip()
    ]
    personal_summary = f"{name}，{job_intent}。"
    project_summary = "普通项目：" + ("、".join(project_names[:6]) if project_names else "暂无可展示项目。")
    work_summary = "工作经历：" + ("、".join(companies[:6]) if companies else "暂无结构化工作经历。")
    strengths: List[str] = []
    if skills:
        strengths.append("技能标签覆盖：" + "、".join(skills[:8]))
    if project_names:
        strengths.append(f"已结构化 {len(project_names)} 个项目，可继续查看证据片段。")
    if companies:
        strengths.append(f"已结构化 {len(companies)} 段工作经历。")
    risks = []
    if not skills:
        risks.append("技能标签为空，需要复核原始简历。")
    if not project_names:
        risks.append("普通项目为空，需要复核项目抽取结果。")
    return SummarySections(
        overall_summary=f"{personal_summary} {project_summary} {work_summary}",
        personal_summary=personal_summary,
        project_summary=project_summary,
        work_experience_summary=work_summary,
        strengths=strengths,
        risks_or_missing_info=risks,
    )


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _model_name(config: Dict[str, Any]) -> str:
    if str(config["model"].get("chat_provider", "") or "") == "openai":
        return str(config["model"].get("openai_model", "") or "")
    return str(config["model"].get("llm_model", "") or "")
