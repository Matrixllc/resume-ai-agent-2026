from __future__ import annotations

import json
from typing import Any, Dict


def build_resume_check_prompt(*, rule_payload: Dict[str, Any], config: Dict[str, Any]) -> str:
    candidate_profile = dict(rule_payload.get("candidate_profile", {}) or {})
    document_profile = dict(rule_payload.get("document_profile", {}) or {})
    work_experiences = list(rule_payload.get("work_experiences", []) or [])[:6]
    education_experiences = list(rule_payload.get("education_experiences", []) or [])[:4]
    project_candidates = list(rule_payload.get("project_candidate_groups", []) or [])[: int(config["ingestion"].get("prompt_max_chunk_candidates", 10))]
    block_actions = list(rule_payload.get("block_actions", []) or [])
    max_context_blocks = max(int(config["ingestion"].get("prompt_max_blocks", 18)) * 4, 80)
    section_is_reliable = str(document_profile.get("value", "")) not in {"messy_resume", "oversized_resume"}
    compact_profile = {
        "contact": {
            "phone": dict(dict(candidate_profile.get("contact", {}) or {}).get("phone", {}) or {}).get("value", ""),
            "email": dict(dict(candidate_profile.get("contact", {}) or {}).get("email", {}) or {}).get("value", ""),
            "wechat": dict(dict(candidate_profile.get("contact", {}) or {}).get("wechat", {}) or {}).get("value", ""),
        },
        "job_intent": dict(candidate_profile.get("job_intent", {}) or {}).get("value", ""),
        "location_raw": dict(candidate_profile.get("location_raw", {}) or {}).get("value", ""),
        "overview_raw": dict(candidate_profile.get("overview_raw", {}) or {}).get("value", "")[:240],
        "resume_level_skills": {
            "raw": list(dict(candidate_profile.get("resume_level_skills", {}) or {}).get("raw", []) or [])[:16],
            "normalized": [item.get("value", "") for item in list(dict(candidate_profile.get("resume_level_skills", {}) or {}).get("normalized", []) or [])[:16]],
        },
        "languages": [item.get("value", "") for item in list(candidate_profile.get("languages", []) or [])[:6]],
        "certifications_or_scores": [item.get("value", "") for item in list(candidate_profile.get("certifications_or_scores", []) or [])[:6]],
        "portfolio_links": [item.get("value", "") for item in list(candidate_profile.get("portfolio_links", []) or [])[:4] if isinstance(item, dict)],
    }
    name_candidates = [
        {
            "value": item.get("value", ""),
            "confidence": item.get("confidence", 0.0),
            "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
            "source": item.get("source", ""),
        }
        for item in list(rule_payload.get("name_candidates", []) or [])
    ] or [
        {
            "value": dict(candidate_profile.get("name", {}) or {}).get("value", ""),
            "confidence": dict(candidate_profile.get("name", {}) or {}).get("confidence", 0.0),
            "evidence_block_ids": list(dict(dict(candidate_profile.get("name", {}) or {}).get("evidence", {}) or {}).get("block_ids", []) or []),
            "source": dict(candidate_profile.get("name", {}) or {}).get("source", ""),
        }
    ]
    compact_work = [
        {
            "work_ref": item.get("work_ref", ""),
            "company_name": item.get("company_name", ""),
            "job_title_raw": item.get("job_title_raw", ""),
            "start_date": item.get("start_date", ""),
            "end_date": item.get("end_date", ""),
            "location": item.get("location", ""),
            "summary_raw": item.get("summary_raw", ""),
            "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
        }
        for item in work_experiences
    ]
    compact_experience_tags = _compact_experience_tags(rule_payload)
    compact_education = [
        {
            "school_name": item.get("school_name", ""),
            "degree": item.get("degree", ""),
            "major": item.get("major", ""),
            "start_date": item.get("start_date", ""),
            "end_date": item.get("end_date", ""),
            "rank_or_gpa": item.get("rank_or_gpa", ""),
            "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
        }
        for item in education_experiences
    ]
    compact_candidates = [
        {
            "block_id": item.get("chunk_id", ""),
            "text": str(item.get("chunk_text", ""))[:700],
            "source_section": item.get("source_section", ""),
            "organization_raw": item.get("organization_raw", ""),
            "date_range_raw": item.get("date_range_raw", ""),
            "rule_tags": [tag.get("value", "") for tag in list(item.get("project_tags", []) or item.get("concept_tags", []) or [])],
            "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
            "confidence": item.get("confidence", 0.0),
        }
        for item in project_candidates
    ]
    compact_context_blocks = [
        {
            "sequence_no": item.get("sequence_no", 0),
            "block_id": item.get("block_id", ""),
            "text": str(item.get("text", ""))[:500],
            "page_no": item.get("page_no", 0),
            "section": item.get("section", ""),
            "block_action": item.get("block_action", ""),
        }
        for item in block_actions[:max_context_blocks]
    ]
    candidate_concepts = sorted(
        {
            item.get("value", "")
            for tag_list in (
                list(rule_payload.get("concept_tags", []) or []),
                list(rule_payload.get("skill_tags", []) or []),
            )
            for item in tag_list
            if item.get("value", "")
        }
    )
    domain_context = {
        "domains": [item.get("value", "") for item in list(rule_payload.get("domain_tags", []) or []) if item.get("value", "")]
    }
    return f"""
你是简历项目结构化助手。请基于规则候选结果完成一次项目解析与归一化。
目标：
1. 判断候选人姓名；
2. 判断一共有几个项目；
3. 为每个项目确认项目名、evidence_block_ids；
4. 对 skill/domain/role 做受限归一化；
5. 不生成项目 summary；
6. 不新增原文不存在的项目、数字成果或技术词。
7. 估算行业/年限经验标签 experience_tags；只输出筛选标签，不修改工作经历日期/公司/岗位。

当前 section 是否可靠：{section_is_reliable}
注意：你只能根据提供的 focus/context blocks 和工作经历候选做判断，不能凭空补字段。

归一化约束：
1. skill_normalized 只能从候选 concepts 中选择；
2. 如果原文出现了技能，但候选 concepts 没有合适 canonical 值，则保留到 skill_raw，skill_normalized 留空；
3. domain_tags 只能从候选领域上下文中的领域名或领域概念中选择；
4. 不允许输出候选集合之外的新 canonical skill 或 domain；
5. 如果拿不准，宁可少填 normalized 字段，也不要自由造词。

工作经历绑定要求：
1. 如果项目来自独立项目经历/校园项目，project_source_type 输出 standalone_project，parent_work_experience_ref 留空；
2. 如果项目明显来自某段工作经历内部，project_source_type 输出 work_embedded_project；
3. 只有当项目与下方某条 work_experience 在公司/岗位/时间/上下文上强绑定时，才填写 parent_work_experience_ref；
4. 不要把纯职责句、岗位标题、教育经历标题当成项目；
5. 不要把一个工作职责句拆成多个相似项目。
6. 工作经历中如果出现独立项目标题行（例如“文档搜索与PDF解析系统开发(Node.js / Next.js)”）且后面有职责/成果说明，应作为 work_embedded_project 输出，并绑定对应 work_ref。
7. 工作经历中只有泛职责描述、没有明确项目标题时，不要为了凑数量生成项目。

非项目硬性排除：
1. 不要把 `框架: ...`、`语言: ...`、`技能: ...`、`TOEFL/GRE/雅思/PMP/CFA`、联系方式、姓名、地点、纯日期、作品集、自我评价当成项目；
2. 如果 evidence_block_ids 只覆盖技能/证书/联系方式/日期/个人信息块，这一项必须不输出到 projects；
3. 技术栈和考试成绩只能进入 resume_level_skills、certifications_or_scores 或 skill_raw，不得作为 project_name_raw。

通用字段输出要求：
1. 如果下方已给出 contact/job_intent/location/overview/work/education 候选，优先保留这些原文可支撑的值；
2. certifications_or_scores 必须输出为字符串数组，例如 ["TOEFL 101", "GRE 321"]，不要输出对象数组；
3. languages、portfolio_links 也必须输出为字符串数组；
4. work_experiences 和 education_experiences 必须按 schema 返回结构化数组，不要只返回空数组占位。
5. 如果 work_experiences 候选为空，但 resume_context_blocks 中能看到公司/岗位/日期行，请从上下文补齐 work_experiences。
6. 如果 education_experiences 候选为空，但 resume_context_blocks 中能看到学校/学位/日期行，请从上下文补齐 education_experiences。

返回 JSON 对象，格式严格如下：
{{
  "selected_name": "",
  "contact": {{"phone": "", "email": "", "wechat": "", "evidence_block_ids": []}},
  "job_intent": {{"job_intent_raw": "", "target_roles": [], "evidence_block_ids": []}},
  "location_raw": "",
  "overview_raw": "",
  "resume_level_skills": {{"raw": [], "normalized": [], "evidence_block_ids": []}},
  "languages": [""],
  "certifications_or_scores": [""],
  "portfolio_links": [""],
  "work_experiences": [
    {{
      "work_ref": "",
      "company_name": "",
      "job_title_raw": "",
      "start_date": "",
      "end_date": "",
      "location": "",
      "summary_raw": "",
      "evidence_block_ids": []
    }}
  ],
  "education_experiences": [
    {{
      "school_name": "",
      "degree": "",
      "major": "",
      "start_date": "",
      "end_date": "",
      "rank_or_gpa": "",
      "evidence_block_ids": []
    }}
  ],
  "experience_tags": [
    {{
      "tag_value": "",
      "confidence": 0.0,
      "evidence_block_ids": [],
      "reason": ""
    }}
  ],
  "project_count": 0,
  "projects": [
    {{
      "project_name_raw": "",
      "project_source_type": "standalone_project",
      "parent_work_experience_ref": "",
      "organization_raw": "",
      "project_date_range_raw": "",
      "evidence_block_ids": [],
      "skill_raw": [],
      "skill_normalized": [],
      "domain_tags": [],
      "role_raw": "",
      "role_normalized": "",
      "achievements_raw": []
    }}
  ]
}}

主分析块（focus_blocks）:
{json.dumps(compact_candidates, ensure_ascii=False, indent=2)}

前文辅助块（leading_blocks）:
{json.dumps(compact_context_blocks[:6], ensure_ascii=False, indent=2)}

后文辅助块（trailing_blocks）:
{json.dumps(compact_context_blocks[6:18], ensure_ascii=False, indent=2)}

简历上下文块（resume_context_blocks，用于补全 work/education/contact/overview）:
{json.dumps(compact_context_blocks, ensure_ascii=False, indent=2)}

通用字段候选（raw-first，能直接用就不要留空）:
{json.dumps(compact_profile, ensure_ascii=False, indent=2)}

工作经历候选（work_experiences，可用于判断 parent_work_experience_ref）:
{json.dumps(compact_work, ensure_ascii=False, indent=2)}

rule 年限经验标签（高置信时不要覆盖；低置信或缺失时可补充估算）:
{json.dumps(compact_experience_tags, ensure_ascii=False, indent=2)}

教育经历候选（education_experiences）:
{json.dumps(compact_education, ensure_ascii=False, indent=2)}

姓名候选（name_candidates）:
{json.dumps(name_candidates, ensure_ascii=False, indent=2)}

通用字段抽取要求：
1. contact 只抽原文可直接定位的 phone/email/wechat；
2. job_intent 只抽求职意向/目标职位类原文；
3. work_experiences 与 education_experiences 采用 raw-first，先抽原文能站住的字段和 evidence；
4. 如果某个字段拿不准，可以留空，不要编造。

候选 concepts:
{json.dumps(candidate_concepts, ensure_ascii=False, indent=2)}

候选领域上下文:
{json.dumps(domain_context, ensure_ascii=False, indent=2)}
""".strip()


def build_project_repair_prompt(*, rule_payload: Dict[str, Any], config: Dict[str, Any]) -> str:
    candidate_profile = dict(rule_payload.get("candidate_profile", {}) or {})
    work_experiences = list(rule_payload.get("work_experiences", []) or [])[:8]
    project_blocks = list(rule_payload.get("project_repair_blocks", []) or []) or list(rule_payload.get("project_section_blocks", []) or [])
    quality = dict(rule_payload.get("project_boundary_quality", {}) or {})
    compact_blocks = [
        {
            "sequence_no": item.get("sequence_no", 0),
            "block_id": item.get("block_id", ""),
            "text": str(item.get("text", ""))[:900],
            "page_no": item.get("page_no", 0),
        }
        for item in project_blocks
    ]
    compact_work = [
        {
            "work_ref": item.get("work_ref", ""),
            "company_name": item.get("company_name", ""),
            "job_title_raw": item.get("job_title_raw", ""),
            "start_date": item.get("start_date", ""),
            "end_date": item.get("end_date", ""),
            "location": item.get("location", ""),
            "summary_raw": str(item.get("summary_raw", "") or "")[:260],
            "raw_line": str(item.get("raw_line", "") or "")[:260],
        }
        for item in work_experiences
    ]
    compact_experience_tags = _compact_experience_tags(rule_payload)
    candidate_concepts = sorted(
        {
            item.get("value", "")
            for tag_list in (
                list(rule_payload.get("concept_tags", []) or []),
                list(rule_payload.get("skill_tags", []) or []),
            )
            for item in tag_list
            if item.get("value", "")
        }
    )
    domain_context = {
        "domains": [item.get("value", "") for item in list(rule_payload.get("domain_tags", []) or []) if item.get("value", "")]
    }
    name = dict(candidate_profile.get("name", {}) or {}).get("value", "")
    return f"""
你是简历项目边界修复助手。本次规则切块不可信，请忽略已有 project candidate 边界，直接根据完整 project_repair_blocks 重新划分项目。

候选人：{name}
触发 repair 的原因：
{json.dumps(quality, ensure_ascii=False, indent=2)}

边界规则：
1. 从 project_repair_blocks 的原始顺序切项目；
2. 项目从真实项目标题开始，到下一个真实项目标题或下一个大 section 前结束；
3. `项目简介/项目介绍/项目描述/项目背景/负责内容/工作内容/职责描述/技术栈/收获总结/项目成果/主要职责` 是项目内部小节，不是新项目；
4. 连续编号条目 `1/2/3` 默认属于当前项目，不能只取第 1 条；
5. 不要把一个编号职责句单独当项目标题，除非它后面跟完整项目说明；
6. 遇到 `## 基于 xxx`、短标题行、bullet 标题行，优先作为项目标题，即使不包含固定关键词；
7. evidence_block_ids 必须覆盖项目标题、项目简介、职责/成果/编号条目；
8. 不新增原文不存在的项目、技术词、成果数字。
9. 不抽取、不改写个人信息、工作经历、教育经历、联系方式、总览；这些字段已经由 rule/layout 负责。
10. 可以输出 experience_tags 作为筛选标签估算；但不能用它反向修改工作经历字段。
11. 工作经历中出现明确项目标题行且后面有职责/成果说明时，可输出 work_embedded_project，并填写 parent_work_experience_ref；
12. 不要把 `框架: ...`、`语言: ...`、`TOEFL/GRE/雅思/PMP/CFA`、联系方式、姓名、地点、纯日期、作品集、自我评价当成项目。

归一化约束：
1. skill_normalized 只能从候选 concepts 中选择；
2. domain_tags 只能从候选领域上下文中的领域名中选择；
3. 原文出现但无法归一化的技术词放到 skill_raw；
4. 工作经历内项目才填写 parent_work_experience_ref；个人/校园/独立项目留空。

返回 JSON 对象，格式严格如下：
{{
  "experience_tags": [
    {{
      "tag_value": "",
      "confidence": 0.0,
      "evidence_block_ids": [],
      "reason": ""
    }}
  ],
  "projects": [
    {{
      "project_name_raw": "",
      "project_source_type": "standalone_project",
      "parent_work_experience_ref": "",
      "organization_raw": "",
      "project_date_range_raw": "",
      "evidence_block_ids": [],
      "skill_raw": [],
      "skill_normalized": [],
      "domain_tags": [],
      "role_raw": "",
      "role_normalized": "",
      "achievements_raw": []
    }}
  ]
}}

project_repair_blocks:
{json.dumps(compact_blocks, ensure_ascii=False, indent=2)}

work_experiences:
{json.dumps(compact_work, ensure_ascii=False, indent=2)}

rule 年限经验标签（高置信时不要覆盖；低置信或缺失时可补充估算）:
{json.dumps(compact_experience_tags, ensure_ascii=False, indent=2)}

候选 concepts:
{json.dumps(candidate_concepts, ensure_ascii=False, indent=2)}

候选领域上下文:
{json.dumps(domain_context, ensure_ascii=False, indent=2)}
""".strip()


def _compact_experience_tags(rule_payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    experience_tags = list(rule_payload.get("experience_tags", []) or [])
    return [
        {
            "tag_value": item.get("value", ""),
            "confidence": item.get("confidence", 0.0),
            "source": item.get("source", ""),
            "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
        }
        for item in experience_tags
    ]
