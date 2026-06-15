from __future__ import annotations

import re
from typing import Any, Dict, List

from resume_query_ai_qa.core.schemas import CandidateScore, EvidenceRef, ResumeQAState


def _used_evidence_refs(state: ResumeQAState) -> List[Dict[str, Any]]:
    refs: List[EvidenceRef] = []
    if state.answer:
        refs.extend(state.answer.used_evidence_refs)
    if not refs:
        refs.extend(_evidence_from_tool_results(state))
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for ref in refs:
        key = ref.evidence_id or f"{ref.resume_identity}:{ref.project_id}:{ref.text[:40]}"
        if key in seen:
            continue
        seen.add(key)
        output.append(_with_evidence_summary(ref).model_dump())
    return output


def _evidence_from_tool_results(state: ResumeQAState) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    for result in state.tool_results:
        if not result.ok:
            continue
        refs.extend(_extract_evidence_refs(result.data))
    return refs


def _extract_evidence_refs(value: Any) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    if isinstance(value, EvidenceRef):
        return [value]
    if isinstance(value, CandidateScore):
        return list(value.evidence_refs)
    if hasattr(value, "model_dump"):
        return _extract_evidence_refs(value.model_dump())
    if isinstance(value, dict):
        if _looks_like_evidence_ref(value):
            try:
                return [EvidenceRef.model_validate(value)]
            except Exception:
                return []
        for item in value.values():
            refs.extend(_extract_evidence_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_extract_evidence_refs(item))
    return refs


def _looks_like_evidence_ref(value: Dict[str, Any]) -> bool:
    return bool({"source_type", "resume_identity", "evidence_id"} & set(value))


def _with_evidence_summary(ref: EvidenceRef) -> EvidenceRef:
    if ref.summary.strip():
        return ref
    subject = ref.candidate_name or "候选人"
    title = ref.project_title or _source_label(ref.source_type)
    text = _clean_evidence_text(ref.text, title)
    if text:
        first = _first_sentence(text)
        summary = f"{subject}在{title}中体现：{first}"
    else:
        summary = f"{subject}的{title}可作为该结论的来源，但原始证据文本较少。"
    if len(summary) > 80:
        summary = summary[:77].rstrip("，。；、 ") + "..."
    return ref.model_copy(update={"summary": summary})


def _first_sentence(text: str) -> str:
    for separator in ["。", "；", ";", "\n"]:
        if separator in text:
            head = text.split(separator, 1)[0].strip()
            if head:
                return head
    return text.strip()


def _clean_evidence_text(value: str, title: str = "") -> str:
    text = " ".join((value or "").replace("\n", " ").split())
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^[-•●\s]+", "", text)
    if title:
        clean_title = " ".join(title.split())
        for prefix in [clean_title, f"{clean_title} -", f"{clean_title}：", f"{clean_title}:"]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip(" -：:")
                break
    text = re.sub(r"\s*[-•●]\s*", "，", text)
    return " ".join(text.split())


def _source_label(source_type: str) -> str:
    return {
        "project_evidence": "项目证据",
        "project_tags": "项目标签",
        "domain_tags": "领域标签",
        "candidate_tags": "候选人标签",
        "work_experiences": "工作经历",
        "education_experiences": "教育经历",
    }.get(str(source_type), "证据")
