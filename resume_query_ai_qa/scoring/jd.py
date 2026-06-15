"""Deterministic JD scoring helpers.

这是一版“可运行但保守”的评分器。它不试图替代招聘专家，也不让 LLM
凭感觉排序；它只把 JD criteria 和候选人证据做规则匹配，然后输出可解释分数。

后续可以把 `extract_jd_criteria` 换成 LLM 结构化抽取，但评分和排序仍应保持
deterministic，确保同一批输入得到同一排序。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import CandidateBrief, CandidateScore, EvidenceRef, JDScoringCriteria


def load_default_jd_criteria(
    target_role: str | None = None,
    job_text: str | None = None,
    config: ResumeQAConfig | None = None,
) -> JDScoringCriteria:
    """Load a matching criteria section from the scoring JD standards file.

    scoring/JD.md 是标准库，不再是单一岗位 JD。传入岗位文本时只解析
    命中的 section；没有命中时回退“通用简历标准”。
    """
    cfg = config or load_config()
    relative = str(cfg.jd_scoring.get("default_jd_path", "resume_query_ai_qa/scoring/JD.md") or "resume_query_ai_qa/scoring/JD.md")
    jd_path = cfg.app_root.parent / relative
    text = jd_path.read_text(encoding="utf-8") if jd_path.exists() else ""
    section_title, text = select_jd_standard_section(text, " ".join(str(item or "") for item in [target_role, job_text]))
    criteria = extract_jd_criteria(text, source="default_jd", config=cfg)
    criteria.target_role = section_title or criteria.target_role or "通用简历标准"
    criteria.required_domains = _domains_for_standard_section(criteria.target_role)
    if criteria.target_role == "通用简历标准":
        criteria.required_skills = []
    return criteria


def load_general_resume_criteria(config: ResumeQAConfig | None = None) -> JDScoringCriteria:
    """在没有 JD 时返回用于排序的通用简历评审标准。"""
    cfg = config or load_config()
    weights = {
        name: float(item.get("weight", 0.0) or 0.0)
        for name, item in dict(cfg.jd_scoring.get("dimensions", {}) or {}).items()
        if isinstance(item, dict)
    }
    return JDScoringCriteria(
        source="manual",
        target_role="通用简历优先级",
        required_domains=[],
        required_skills=[],
        preferred_skills=[],
        experience_signals=[],
        risk_signals=["缺少项目证据", "关键信息缺失"],
        scoring_weights=weights,
    )


def extract_jd_criteria(
    jd_text: str,
    *,
    source: str = "user_jd",
    config: ResumeQAConfig | None = None,
) -> JDScoringCriteria:
    """Extract a conservative criteria object from JD text.

    这里故意只做关键词规则抽取。第一版不让 LLM 自由决定评分维度，
    避免排序口径漂移。后续接 LLM 时也要输出同一个 schema。
    """
    cfg = config or load_config()
    text = jd_text or ""
    known_domains = {
        "Finance": ["finance", "金融", "交易", "风控", "支付", "投研", "量化", "股票", "信贷"],
        "Operations": ["operations", "运营", "增长", "用户", "活动", "商家", "会员"],
        "Energy": ["energy", "能源", "新能源", "电力", "储能", "风电", "光伏", "碳资产", "碳交易"],
        "Backend": ["backend", "后端", "服务端", "系统设计", "接口", "数据库", "中间件"],
        "AI Search": ["ai search", "搜索", "检索", "推荐", "召回", "rag", "llm", "向量检索", "agent"],
    }
    known_skills = [
        "Python",
        "Java",
        "JavaScript",
        "Node.js",
        "SQL",
        "MySQL",
        "Redis",
        "Kafka",
        "MongoDB",
        "Spring Boot",
        "RAG",
        "LLM",
        "Embedding",
        "向量检索",
        "推荐系统",
        "搜索系统",
        "Golang",
        "Go",
        "消息队列",
        "线程池",
        "接口设计",
        "系统设计",
        "数据分析",
        "风控",
        "量化",
        "电力交易",
        "用户增长",
    ]
    required_domains = [
        domain
        for domain, aliases in known_domains.items()
        if _matches_any(text, aliases)
    ]
    required_skills = [
        skill
        for skill in known_skills
        if _normalize_key(skill) in _normalize_key(text)
    ]
    weights = {
        name: float(item.get("weight", 0.0) or 0.0)
        for name, item in dict(cfg.jd_scoring.get("dimensions", {}) or {}).items()
        if isinstance(item, dict)
    }
    return JDScoringCriteria(
        source=source if source in {"user_jd", "default_jd", "manual"} else "user_jd",
        target_role=_guess_target_role(text),
        required_domains=required_domains,
        required_skills=required_skills,
        preferred_skills=[],
        experience_signals=_terms_from_text(text),
        risk_signals=["缺少项目证据", "关键信息缺失"],
        scoring_weights=weights,
    )


def select_jd_standard_section(jd_text: str, target_text: str = "") -> tuple[str, str]:
    """Select one standards-library section by target text, falling back to general."""
    sections = _split_markdown_sections(jd_text)
    if not sections:
        return "通用简历标准", jd_text
    normalized_target = _normalize_key(target_text)
    section_aliases = [
        ("金融岗位标准", ["金融", "金融分析", "风控", "交易", "投研", "支付", "量化", "finance"]),
        ("运营岗位标准", ["运营", "用户运营", "活动运营", "增长", "商家运营", "会员运营", "operations"]),
        ("能源岗位标准", ["能源", "新能源", "电力", "储能", "风电", "光伏", "碳资产", "energy"]),
        ("后端开发岗位标准", ["后端", "后端开发", "服务端", "backend", "java后端", "golang后端", "node.js后端"]),
        ("AI/AI Search 岗位标准", ["ai", "ai search", "搜索", "推荐", "召回", "排序", "rag", "llm", "向量检索", "机器学习"]),
    ]
    for title, aliases in section_aliases:
        if _matches_any(normalized_target, aliases) and title in sections:
            return title, sections[title]
    return "通用简历标准", sections.get("通用简历标准") or next(iter(sections.values()))


def _split_markdown_sections(text: str) -> dict[str, str]:
    """Split first-level markdown sections while preserving each selected heading."""
    sections: dict[str, str] = {}
    current_title = ""
    current_lines: list[str] = []
    for line in str(text or "").splitlines():
        if line.startswith("# "):
            if current_title:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line.removeprefix("# ").strip()
            current_lines = [line]
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _domains_for_standard_section(title: str) -> list[str]:
    """Return section-owned domains without leaking example terms across roles."""
    mapping = {
        "金融岗位标准": ["Finance"],
        "运营岗位标准": ["Operations"],
        "能源岗位标准": ["Energy"],
        "后端开发岗位标准": ["Backend"],
        "AI/AI Search 岗位标准": ["AI Search"],
        "通用简历标准": [],
    }
    return list(mapping.get(str(title or ""), []))


def score_candidate_material_for_jd(
    brief: CandidateBrief,
    evidence_refs: List[EvidenceRef],
    criteria: JDScoringCriteria | Dict[str, Any],
    config: ResumeQAConfig | None = None,
) -> CandidateScore:
    """Score one already-loaded candidate against criteria with evidence.

    分数只是排序工具的中间结果，不是最终招聘结论。每个加分项尽量保留
    evidence_refs，方便答案阶段解释“为什么是这个分数”。
    """
    parsed = _criteria(criteria)
    if _is_general_resume_criteria(parsed):
        return _score_candidate_for_general_resume(brief, evidence_refs, parsed)
    searchable = _candidate_text(brief, evidence_refs)
    weights = parsed.scoring_weights

    domain_score, domain_strengths = _dimension_overlap_score(
        parsed.required_domains,
        brief.domains,
        weights.get("domain_match", 30.0),
    )
    skill_score, skill_strengths = _dimension_overlap_score(
        parsed.required_skills,
        brief.skills,
        weights.get("required_skill_match", 25.0),
    )
    project_score, project_strengths = _project_evidence_score(
        parsed.required_domains + parsed.required_skills + parsed.experience_signals,
        evidence_refs,
        weights.get("project_jd_evidence", 40.0),
    )
    work_score = _work_experience_years_score(
        brief.resume_identity,
        parsed.experience_signals,
        weights.get("work_experience_years", 15.0),
    )
    communication_score = _communication_score(searchable, weights.get("communication_or_language", 5.0))
    risk_penalty, risks = _risk_penalty(parsed, brief, evidence_refs, weights.get("risk_penalty", -10.0))
    dimension_scores = {
        "domain_match": domain_score,
        "required_skill_match": skill_score,
        "project_jd_evidence": project_score,
        "work_experience_years": work_score,
        "communication_or_language": communication_score,
        "risk_penalty": risk_penalty,
    }
    total = sum(dimension_scores.values())
    return CandidateScore(
        resume_identity=brief.resume_identity,
        name=brief.name,
        total_score=round(max(total, 0.0), 2),
        dimension_scores={key: round(value, 2) for key, value in dimension_scores.items()},
        strengths=project_strengths + domain_strengths + skill_strengths,
        risks=risks,
        evidence_refs=evidence_refs[:5],
        missing_info=_missing_info(parsed, brief),
        recommendation_reason=_recommendation_reason(project_strengths + domain_strengths + skill_strengths, risks),
    )


def rank_candidates(scored_candidates: List[CandidateScore] | List[Dict[str, Any]]) -> List[CandidateScore]:
    """对已有 CandidateScore 排序。

    这里不重新打分，只按确定性 key 排序。aggregator 必须保留这个顺序，不能因为
    文案表达需要重排候选人。
    """
    parsed = [
        item if isinstance(item, CandidateScore) else CandidateScore.model_validate(item)
        for item in scored_candidates
    ]
    ranked = sorted(parsed, key=_ranking_key)
    if len(ranked) >= 2 and ranked[0].total_score == ranked[1].total_score:
        top = ranked[0]
        reason = _tie_break_reason(top, ranked[1])
        ranked[0] = top.model_copy(update={"tie_break_reason": reason})
    return ranked


def _is_general_resume_criteria(criteria: JDScoringCriteria) -> bool:
    """判断 criteria 是否表示“无明确 JD 的通用简历优先级”。"""
    return criteria.target_role in {"通用简历优先级", "通用简历标准"} or (
        criteria.source == "manual"
        and not criteria.required_domains
        and not criteria.required_skills
        and not criteria.experience_signals
    )


def _score_candidate_for_general_resume(
    brief: Any,
    evidence_refs: List[EvidenceRef],
    criteria: JDScoringCriteria,
) -> CandidateScore:
    """按通用简历标准计算候选人评分并返回。"""
    weights = criteria.scoring_weights
    project_weight = weights.get("project_jd_evidence", 40.0)
    domain_weight = weights.get("domain_match", 30.0)
    skill_weight = weights.get("required_skill_match", 25.0)
    work_weight = weights.get("work_experience_years", 15.0)
    risk_weight = weights.get("risk_penalty", -10.0)

    evidence_score = project_weight * min(len(evidence_refs) / 5.0, 1.0)
    domain_score = domain_weight * min(len(getattr(brief, "domains", []) or []) / 4.0, 1.0)
    skill_score = skill_weight * min(len(getattr(brief, "skills", []) or []) / 8.0, 1.0)
    work_score = work_weight * min(float(getattr(brief, "work_count", 0) or 0) / 4.0, 1.0)
    risks: List[str] = []
    risk_penalty = 0.0
    if not evidence_refs:
        risks.append("缺少项目级证据，通用优先级需要谨慎判断")
        risk_penalty += risk_weight * 0.6
    if not getattr(brief, "skills", []) and not getattr(brief, "domains", []):
        risks.append("技能/领域标签不足")
        risk_penalty += risk_weight * 0.4

    strengths: List[str] = []
    if evidence_refs:
        strengths.append(f"有 {len(evidence_refs)} 条项目/经历证据可用于判断")
    if getattr(brief, "work_count", 0):
        strengths.append(f"工作经历 {brief.work_count} 段")
    if getattr(brief, "project_count", 0):
        strengths.append(f"项目记录 {brief.project_count} 个")
    if getattr(brief, "skills", []):
        strengths.append("技能覆盖：" + "、".join(str(item) for item in brief.skills[:5]))
    dimension_scores = {
        "project_jd_evidence": evidence_score,
        "domain_match": domain_score,
        "required_skill_match": skill_score,
        "work_experience_years": work_score,
        "communication_or_language": 0.0,
        "risk_penalty": risk_penalty,
    }
    total = sum(dimension_scores.values())
    return CandidateScore(
        resume_identity=brief.resume_identity,
        name=brief.name,
        total_score=round(max(total, 0.0), 2),
        dimension_scores={key: round(value, 2) for key, value in dimension_scores.items()},
        strengths=strengths,
        risks=risks,
        evidence_refs=evidence_refs[:5],
        missing_info=[] if evidence_refs else ["缺少可复核的项目级证据"],
        recommendation_reason=_recommendation_reason(strengths, risks) or "按通用简历完整度、项目证据、技能覆盖和风险缺口排序。",
    )


def _ranking_key(item: CandidateScore) -> tuple:
    """生成稳定排序 key，确保同分时也能得到可复现顺序。"""
    scores = item.dimension_scores or {}
    return (
        -item.total_score,
        -float(scores.get("project_jd_evidence", 0.0) or 0.0),
        -float(scores.get("domain_match", 0.0) or 0.0),
        -float(scores.get("required_skill_match", 0.0) or 0.0),
        -float(scores.get("work_experience_years", 0.0) or 0.0),
        float(scores.get("risk_penalty", 0.0) or 0.0),
        -len(item.evidence_refs or []),
        -len(item.strengths or []),
        item.name,
        item.resume_identity,
    )


def _tie_break_reason(winner: CandidateScore, runner_up: CandidateScore) -> str:
    """第一、第二名总分相同时，给出当前排序的可解释 tie-break 原因。"""
    dimensions = [
        ("project_jd_evidence", "项目证据强度更高"),
        ("domain_match", "领域匹配更高"),
        ("required_skill_match", "技能覆盖更高"),
        ("work_experience_years", "工作经历完整度更高"),
    ]
    winner_scores = winner.dimension_scores or {}
    runner_scores = runner_up.dimension_scores or {}
    for key, label in dimensions:
        if float(winner_scores.get(key, 0.0) or 0.0) > float(runner_scores.get(key, 0.0) or 0.0):
            return f"总分相同，按 tie-break 规则选择：{label}。"
    if float(winner_scores.get("risk_penalty", 0.0) or 0.0) > float(runner_scores.get("risk_penalty", 0.0) or 0.0):
        return "总分相同，按 tie-break 规则选择：风险扣分更少。"
    if len(winner.evidence_refs or []) > len(runner_up.evidence_refs or []):
        return "总分相同，按 tie-break 规则选择：可复核证据更多。"
    return "总分相同，按稳定排序规则给出当前优先推荐。"


def _recommendation_reason(strengths: List[str], risks: List[str]) -> str:
    """从 strengths / risks 中压缩出一句可展示的推荐理由。"""
    if strengths:
        return "；".join(strengths[:2])
    if risks:
        return "主要风险：" + "；".join(risks[:2])
    return ""


def _criteria(value: JDScoringCriteria | Dict[str, Any]) -> JDScoringCriteria:
    """把 dict 或 Pydantic 对象统一转换为 JDScoringCriteria。"""
    if isinstance(value, JDScoringCriteria):
        return value
    return JDScoringCriteria.model_validate(value)


def _dimension_overlap_score(required: List[str], actual: List[str], weight: float) -> tuple[float, List[str]]:
    """按 required 与 actual 的标准化重合度计算单个维度分数。"""
    if not required:
        return 0.0, []
    actual_keys = {_normalize_key(item) for item in actual}
    matched = [item for item in required if _normalize_key(item) in actual_keys]
    score = weight * (len(matched) / max(len(required), 1))
    strengths = [f"命中 {item}" for item in matched]
    return score, strengths


def _project_evidence_score(terms: List[str], refs: List[EvidenceRef], weight: float) -> tuple[float, List[str]]:
    """检查 evidence 文本是否命中 JD 词项，并计算项目证据维度分数。"""
    if not terms:
        return 0.0, []
    matched: List[str] = []
    for term in terms:
        normalized_term = _normalize_key(term)
        if not normalized_term:
            continue
        for ref in refs:
            evidence_text = " ".join([ref.text, ref.project_title, ref.project_id])
            if normalized_term in _normalize_key(evidence_text):
                matched.append(term)
                break
    score = weight * min(len(matched) / max(len(terms), 1), 1.0)
    strengths = [f"项目证据命中 JD 关键词：{term}" for term in matched[:5]]
    return score, strengths


def _work_experience_years_score(resume_identity: str, terms: List[str], weight: float) -> float:
    """读取候选人工作经历并计算年限得分；资料不可读时保守返回 0 分。"""
    from resume_query_tools import get_candidate_profile

    try:
        detail = get_candidate_profile(resume_identity)
    except Exception:
        # JD 年限评分不能猜测工作年限；profile 读取失败时只放弃该维度，不影响其他维度。
        return 0.0
    work_items = list(getattr(detail, "work_experiences", []) or [])
    if not work_items:
        return 0.0
    years = _estimate_work_years(work_items)
    if years <= 0:
        # Conservative baseline when dates are missing: work history exists, but
        # we do not infer seniority beyond count.
        years = min(len(work_items), 3) * 0.75
    # Four years is treated as full credit for the first deterministic version.
    return weight * min(years / 4.0, 1.0)


def _estimate_work_years(work_items: Iterable[Any]) -> float:
    """从工作经历日期文本中保守估算年限；无法识别时返回 0。"""
    total_months = 0
    for item in work_items:
        text = _work_item_date_text(item)
        years = [int(match) for match in re.findall(r"(?:19|20)\d{2}", text)]
        if len(years) >= 2:
            start, end = min(years), max(years)
            total_months += max((end - start) * 12, 0)
        elif len(years) == 1 and any(token in text for token in ["至今", "present", "now", "当前"]):
            total_months += max((2026 - years[0]) * 12, 0)
    return round(total_months / 12.0, 2)


def _work_item_date_text(item: Any) -> str:
    """从工作经历对象中提取日期/周期相关文本，供年限估算使用。"""
    if hasattr(item, "model_dump"):
        item = item.model_dump()
    if isinstance(item, dict):
        parts = [
            str(value)
            for key, value in item.items()
            if "date" in str(key).lower() or "time" in str(key).lower() or "period" in str(key).lower()
        ]
        if parts:
            return " ".join(parts)
        return " ".join(str(value) for value in item.values())
    return str(item)


def _communication_score(text: str, weight: float) -> float:
    """命中语言、沟通、文档等信号时给出沟通/语言维度分。"""
    signals = ["英语", "english", "沟通", "文档", "海外", "toefl", "gre"]
    return weight if _matches_any(text, signals) else 0.0


def _risk_penalty(
    criteria: JDScoringCriteria,
    brief: Any,
    refs: List[EvidenceRef],
    weight: float,
) -> tuple[float, List[str]]:
    """根据缺少领域、技能或项目证据等情况计算风险扣分。"""
    risks: List[str] = []
    if criteria.required_domains and not brief.domains:
        risks.append("缺少领域标签")
    if criteria.required_skills and not brief.skills:
        risks.append("缺少技能标签")
    if not refs:
        risks.append("缺少项目级证据")
    if not risks:
        return 0.0, []
    # weight 是负数；风险越多，最多扣到这个负权重。
    ratio = min(len(risks) / 3, 1.0)
    return weight * ratio, risks


def _missing_info(criteria: JDScoringCriteria, brief: Any) -> List[str]:
    """列出影响评分可信度的缺失字段。"""
    missing: List[str] = []
    if criteria.required_domains and not brief.domains:
        missing.append("domain")
    if criteria.required_skills and not brief.skills:
        missing.append("skills")
    if not brief.project_count:
        missing.append("projects")
    return missing


def _candidate_text(brief: Any, refs: List[EvidenceRef]) -> str:
    """拼接候选人 brief 和 evidence，供轻量信号匹配使用。"""
    return "\n".join(
        [
            brief.name,
            brief.job_intent,
            brief.location_raw,
            " ".join(brief.skills),
            " ".join(brief.domains),
            "\n".join(ref.text for ref in refs),
        ]
    )


def _guess_target_role(text: str) -> str:
    """从 JD 文本中保守判断是否存在目标岗位描述。"""
    for marker in ["岗位", "职位", "目标"]:
        if marker in text:
            return "JD 目标岗位"
    return ""


def _terms_from_text(text: str) -> List[str]:
    """从文本中提取标准化词项并返回。"""
    terms = [item for item in re.split(r"[\s,，。；;、/()（）]+", text) if len(item.strip()) >= 2]
    output: List[str] = []
    seen = set()
    for term in terms:
        key = _normalize_key(term)
        if key in seen:
            continue
        seen.add(key)
        output.append(term)
    return output[:20]


def _matches_any(text: str, terms: Iterable[str]) -> bool:
    """判断文本是否命中任一词项并返回布尔值。"""
    normalized = _normalize_key(text)
    return any(_normalize_key(term) in normalized for term in terms if str(term).strip())


def _normalize_key(value: str) -> str:
    """标准化匹配键并返回。"""
    return re.sub(r"\s+", "", str(value or "")).lower()
