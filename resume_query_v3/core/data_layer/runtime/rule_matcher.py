from __future__ import annotations

import re
import statistics
import subprocess
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..pipeline_yaml import ChunkingConfig, DomainConfig, RoutingConfig, SectionAliasConfig
from ..schemas import DocumentBlock, build_evidence, make_scored_value

DATE_RANGE_RE = re.compile(
    r"(?P<start>(?:19|20)\d{2}(?:[./-]?\d{1,2}){0,2})\s*(?:(?:至|到|-|–|—|~|to)\s*)?(?P<end>至今|present|current|(?:19|20)\d{2}(?:[./-]?\d{1,2}){0,2})",
    re.IGNORECASE,
)
MONTH_DATE_RANGE_RE = re.compile(
    r"(?P<start_month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s*(?P<start_year>(?:19|20)\d{2})?\s*[-–—]\s*(?P<end_month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s*(?P<end_year>(?:19|20)\d{2})",
    re.IGNORECASE,
)
MONTH_TO_PRESENT_RE = re.compile(
    r"(?P<start_month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s*(?P<start_year>(?:19|20)\d{2})\s*[-–—]\s*(?P<end>present|current|至今)",
    re.IGNORECASE,
)
MONTH_NAME_TO_NUMBER = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "sept": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://\S+")
WECHAT_RE = re.compile(r"(?:wechat|微信)[:：]?\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)


def build_rule_candidates(
    *,
    blocks: List[DocumentBlock],
    file_path: Path,
    section_config: SectionAliasConfig,
    routing_config: RoutingConfig,
    chunking_config: ChunkingConfig,
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
) -> Dict[str, Any]:
    sections = _detect_sections(blocks, section_config)
    metrics = _compute_document_metrics(blocks, sections, routing_config)
    document_profile = _classify_document_profile(metrics, routing_config)
    block_actions = _score_and_route_blocks(
        blocks=blocks,
        sections=sections,
        chunking_config=chunking_config,
        concepts=concepts,
        domains=domains,
        profile=document_profile["profile"],
    )
    selected_blocks, dropped_blocks = _apply_block_budget(
        block_actions=block_actions,
        chunking_config=chunking_config,
        profile=document_profile["profile"],
    )
    profile_evidence = build_evidence(selected_blocks[: min(6, len(selected_blocks))] or blocks[: min(6, len(blocks))])
    contact = _extract_contact_info(blocks)
    job_intent = _extract_job_intent(blocks)
    overview = _extract_overview(blocks, sections)
    location = _extract_location(blocks)
    layout_lines = _extract_pdf_layout_lines(blocks)
    skills = _extract_skill_tags(selected_blocks or blocks, concepts, layout_lines=layout_lines)
    languages = _extract_language_tags(blocks)
    certifications = _extract_certifications(blocks)
    portfolio_links = _extract_portfolio_links(blocks)
    work_experiences = _extract_work_experiences(blocks, section_config, layout_lines=layout_lines)
    education_experiences = _extract_education_experiences(blocks, section_config, layout_lines=layout_lines)
    concept_tags, domain_tags = _extract_concept_and_domain_tags(selected_blocks or blocks, concepts, domains)
    experience_tags = _extract_experience_tags(work_experiences=work_experiences, domain_tags=domain_tags)
    project_candidate_groups = _build_chunk_candidates(
        blocks,
        sections,
        chunking_config,
        concepts,
        domains,
        work_experiences=work_experiences,
    )
    project_candidate_groups = _apply_layout_project_dates(project_candidate_groups, layout_lines)
    project_section_blocks = _project_section_blocks_from_actions(block_actions)
    project_boundary_quality = _assess_project_boundary_quality(
        project_section_blocks=project_section_blocks,
        project_candidate_groups=project_candidate_groups,
    )
    project_repair_blocks = project_section_blocks
    if project_boundary_quality.get("status") == "repair_required" and not project_repair_blocks:
        project_repair_blocks = _project_repair_blocks_from_actions(block_actions)
        if project_repair_blocks:
            project_boundary_quality = {
                **project_boundary_quality,
                "repair_source": "work_section",
                "repair_source_block_count": len(project_repair_blocks),
            }
    else:
        project_boundary_quality = {
            **project_boundary_quality,
            "repair_source": "project_section" if project_repair_blocks else "",
            "repair_source_block_count": len(project_repair_blocks),
        }
    name_candidates = _extract_name_candidates(blocks, file_path, layout_lines=layout_lines)
    candidate_name = name_candidates[0] if name_candidates else _extract_name(blocks, file_path)
    return {
        "name_candidates": name_candidates,
        "candidate_profile": {
            "name": candidate_name,
            "contact": contact,
            "job_intent": job_intent,
            "location_raw": location,
            "overview_raw": overview,
            "resume_level_skills": skills,
            "languages": languages,
            "certifications_or_scores": certifications,
            "portfolio_links": portfolio_links,
        },
        "work_experiences": work_experiences,
        "education_experiences": education_experiences,
        "concept_tags": concept_tags,
        "domain_tags": domain_tags,
        "experience_tags": experience_tags,
        "skill_tags": skills.get("normalized", []),
        "document_profile": make_scored_value(
            value=document_profile["profile"],
            confidence=document_profile["confidence"],
            evidence=profile_evidence,
            source="rule",
            extra={"metrics": metrics, "reasons": document_profile["reasons"]},
        ),
        "selected_blocks": [block.to_dict() for block in selected_blocks],
        "dropped_blocks": dropped_blocks,
        "block_actions": block_actions,
        "project_section_blocks": project_section_blocks,
        "project_repair_blocks": project_repair_blocks,
        "project_boundary_quality": project_boundary_quality,
        "project_cleanup_config": dict(chunking_config.project_cleanup or {}),
        "project_candidate_groups": project_candidate_groups,
        "compression_ratio": round(1.0 - (len(selected_blocks) / max(1, len(blocks))), 4),
        "resolve_mode": "rule_candidates",
    }


def _detect_sections(blocks: List[DocumentBlock], config: SectionAliasConfig) -> Dict[str, List[str]]:
    section_map = {
        "work": {_normalize_heading(item) for item in config.work_sections},
        "education": {_normalize_heading(item) for item in config.education_sections},
        "skill": {_normalize_heading(item) for item in config.skill_sections},
        "project": {_normalize_heading(item) for item in config.project_sections},
        "summary": {_normalize_heading(item) for item in config.summary_sections},
    }
    current = ""
    results = {key: [] for key in section_map}
    for seq, block in enumerate(blocks):
        normalized = _normalize_heading(block.text)
        for section_name, titles in section_map.items():
            if normalized in titles:
                current = section_name
                break
        if current:
            results[current].append(block.block_id)
    return results


def _compute_document_metrics(
    blocks: List[DocumentBlock],
    sections: Dict[str, List[str]],
    routing_config: RoutingConfig,
) -> Dict[str, Any]:
    texts = [block.text.strip() for block in blocks if block.text.strip()]
    block_count = len(texts)
    avg_block_length = int(statistics.mean(len(text) for text in texts)) if texts else 0
    duplicates = block_count - len(set(texts))
    duplicate_ratio = round(duplicates / max(1, block_count), 4)
    section_hits = sum(1 for item in sections.values() if item)
    section_hit_rate = round(section_hits / 5.0, 4)
    non_alnum = sum(sum(1 for ch in text if not ch.isalnum() and not ch.isspace()) for text in texts)
    total_chars = max(1, sum(len(text) for text in texts))
    ocr_noise_ratio = round(non_alnum / total_chars, 4)
    english_chars = sum(sum(1 for ch in text if "LATIN" in unicodedata.name(ch, "")) for text in texts)
    chinese_chars = sum(sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff") for text in texts)
    mixed_language_ratio = round(min(english_chars, chinese_chars) / max(1, english_chars + chinese_chars), 4)
    estimated_tokens = int(total_chars / 1.6)
    return {
        "block_count": block_count,
        "avg_block_length": avg_block_length,
        "duplicate_ratio": duplicate_ratio,
        "section_hit_rate": section_hit_rate,
        "ocr_noise_ratio": ocr_noise_ratio,
        "mixed_language_ratio": mixed_language_ratio,
        "estimated_tokens": estimated_tokens,
        "routing_thresholds": {
            "oversized_block_count": routing_config.oversized_block_count,
            "oversized_token_budget": routing_config.oversized_token_budget,
        },
    }


def _classify_document_profile(metrics: Dict[str, Any], config: RoutingConfig) -> Dict[str, Any]:
    reasons: List[str] = []
    if metrics["block_count"] >= config.oversized_block_count or metrics["estimated_tokens"] >= config.oversized_token_budget:
        reasons.append("budget_exceeded")
        return {"profile": "oversized_resume", "confidence": 0.9, "reasons": reasons}
    if metrics["section_hit_rate"] < config.messy_min_section_hit_rate or metrics["duplicate_ratio"] >= config.messy_duplicate_ratio:
        reasons.append("low_section_quality")
        return {"profile": "messy_resume", "confidence": 0.78, "reasons": reasons}
    if metrics["block_count"] >= config.dense_block_count or metrics["avg_block_length"] >= config.dense_avg_block_length:
        reasons.append("high_information_density")
        return {"profile": "dense_resume", "confidence": 0.82, "reasons": reasons}
    reasons.append("normal_layout")
    return {"profile": "standard_resume", "confidence": 0.88, "reasons": reasons}


def _score_and_route_blocks(
    *,
    blocks: List[DocumentBlock],
    sections: Dict[str, List[str]],
    chunking_config: ChunkingConfig,
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
    profile: str,
) -> List[Dict[str, Any]]:
    duplicate_counts: Dict[str, int] = {}
    for block in blocks:
        duplicate_counts[block.text.strip()] = duplicate_counts.get(block.text.strip(), 0) + 1
    section_lookup = {block_id: section_name for section_name, block_ids in sections.items() for block_id in block_ids}
    actions: List[Dict[str, Any]] = []
    for seq, block in enumerate(blocks):
        text = block.text.strip()
        lower = text.lower()
        section_name = section_lookup.get(block.block_id, "")
        concept_hits = _collect_concept_hits(text, concepts)
        domain_hits = _collect_domain_hits(text, domains)
        score = 0.2 + min(0.3, 0.08 * len(concept_hits)) + min(0.2, 0.1 * len(domain_hits))
        if section_name in set(chunking_config.mandatory_sections):
            score += 0.35
        if _looks_like_experience_line(text):
            score += 0.18
        action = "keep"
        reasons: List[str] = []
        if duplicate_counts.get(text, 0) > 1 and (PHONE_RE.search(text) or EMAIL_RE.search(text)):
            action = "hard_drop"
            reasons.append("duplicate_contact")
        elif _is_decorative_block(text) or any(pattern.lower() in lower for pattern in chunking_config.hard_drop_patterns):
            action = "hard_drop"
            reasons.append("decorative_or_noise")
        elif any(pattern.lower() in lower for pattern in chunking_config.soft_downgrade_patterns) and not concept_hits and section_name not in {"work", "education", "project"}:
            action = "soft_downgrade"
            reasons.append("low_information_summary")
            score -= 0.22
        elif len(text) > 180 and not concept_hits and section_name not in {"work", "education", "project"}:
            action = "soft_downgrade"
            reasons.append("long_unstructured_text")
            score -= 0.18
        elif profile in {"messy_resume", "dense_resume"} and concept_hits and section_name not in {"work", "education", "project", "skill"}:
            action = "llm_review"
            reasons.append("ambiguous_but_relevant")
            score += 0.08
        actions.append(
            {
                "sequence_no": seq,
                "block_id": block.block_id,
                "text": text,
                "page_no": block.page_no,
                "section": section_name,
                "block_score": round(max(0.0, min(score, 0.99)), 4),
                "block_action": action,
                "action_reason": reasons or ["default_keep"],
                "concept_hits": concept_hits,
                "domain_hits": domain_hits,
            }
        )
    return actions


def _apply_block_budget(
    *,
    block_actions: List[Dict[str, Any]],
    chunking_config: ChunkingConfig,
    profile: str,
) -> Tuple[List[DocumentBlock], List[Dict[str, Any]]]:
    budget = chunking_config.standard_block_budget
    if profile == "dense_resume":
        budget = chunking_config.dense_block_budget
    elif profile == "oversized_resume":
        budget = chunking_config.oversized_block_budget
    kept_candidates = [item for item in block_actions if item["block_action"] in {"keep", "llm_review"}]
    downgraded = [item for item in block_actions if item["block_action"] == "soft_downgrade"]
    dropped = [item for item in block_actions if item["block_action"] == "hard_drop"]
    sorted_candidates = sorted(
        kept_candidates + downgraded,
        key=lambda item: (
            0 if item["section"] in {"work", "education", "project", "skill"} else 1,
            -float(item["block_score"]),
        ),
    )
    selected_meta = sorted_candidates[:budget]
    selected_ids = {item["block_id"] for item in selected_meta}
    selected_meta = sorted(selected_meta, key=lambda item: int(item.get("sequence_no", 0)))
    selected_blocks = [
        DocumentBlock(
            block_id=item["block_id"],
            page_no=int(item["page_no"]),
            text=item["text"],
            raw_text=item["text"],
            source_file="",
        )
        for item in selected_meta
    ]
    dropped_payload = [
        {**item, "dropped_by_budget": item["block_id"] not in selected_ids}
        for item in dropped + [entry for entry in sorted_candidates[budget:]]
    ]
    return selected_blocks, dropped_payload


def _extract_name(blocks: List[DocumentBlock], file_path: Path) -> Dict[str, Any]:
    candidates = _extract_name_candidates(blocks, file_path)
    if candidates:
        return candidates[0]
    stem = file_path.stem.split("-", 1)[0].strip()
    return make_scored_value(value=stem, confidence=0.45, evidence={"block_ids": [], "text_snippets": [], "page_refs": []}, source="filename_fallback")


def _extract_name_candidates(blocks: List[DocumentBlock], file_path: Path, *, layout_lines: List[str] | None = None) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for line in list(layout_lines or [])[:5]:
        normalized = _normalize_content_text(line)
        if _looks_like_name(normalized) and normalized not in seen:
            seen.add(normalized)
            candidates.append(
                make_scored_value(
                    value=normalized,
                    confidence=0.98,
                    evidence={"block_ids": [], "text_snippets": [normalized], "page_refs": []},
                    source="layout_rule",
                )
            )
            break
    for index, block in enumerate(blocks[:80]):
        text = _clean_heading_text(block.text)
        if _looks_like_name(text):
            normalized = _normalize_content_text(text)
            if normalized and normalized not in seen:
                seen.add(normalized)
                if _has_contact_or_intent_nearby(blocks, index):
                    confidence = 0.96
                elif re.fullmatch(r"[\u4e00-\u9fff]{2,4}", normalized):
                    confidence = 0.82
                else:
                    confidence = 0.62
                candidates.append(make_scored_value(value=normalized, confidence=confidence, evidence=build_evidence([block]), source="rule"))
    stem = file_path.stem.split("-", 1)[0].strip()
    if stem and stem not in seen:
        candidates.append(make_scored_value(value=stem, confidence=0.45, evidence={"block_ids": [], "text_snippets": [], "page_refs": []}, source="filename_fallback"))
    return sorted(candidates, key=lambda item: float(item.get("confidence", 0.0) or 0.0), reverse=True)[:4]


def _extract_contact_info(blocks: List[DocumentBlock]) -> Dict[str, Any]:
    phone = ""
    email = ""
    wechat = ""
    evidence_blocks: List[DocumentBlock] = []
    for block in blocks[:12]:
        text = _normalize_content_text(block.text)
        if not phone:
            match = PHONE_RE.search(text)
            if match:
                phone = match.group(1)
                evidence_blocks.append(block)
        if not email:
            match = EMAIL_RE.search(text)
            if match:
                email = match.group(0)
                evidence_blocks.append(block)
        if not wechat:
            match = WECHAT_RE.search(text)
            if match:
                wechat = match.group(1)
                evidence_blocks.append(block)
    return {
        "phone": make_scored_value(value=phone, confidence=0.94 if phone else 0.0, evidence=build_evidence(evidence_blocks[:1]), source="rule"),
        "email": make_scored_value(value=email, confidence=0.94 if email else 0.0, evidence=build_evidence(evidence_blocks[1:2] or evidence_blocks[:1]), source="rule"),
        "wechat": make_scored_value(value=wechat, confidence=0.9 if wechat else 0.0, evidence=build_evidence(evidence_blocks[-1:]), source="rule"),
    }


def _extract_job_intent(blocks: List[DocumentBlock]) -> Dict[str, Any]:
    for block in blocks[:14]:
        text = _normalize_content_text(block.text)
        if any(token in text for token in ("求职意向", "目标职位", "应聘岗位", "job intent")):
            value = text.split("：", 1)[-1].split(":", 1)[-1].strip()
            return make_scored_value(value=value, confidence=0.84, evidence=build_evidence([block]), source="rule")
    return make_scored_value(value="", confidence=0.0, evidence={"block_ids": [], "text_snippets": [], "page_refs": []}, source="rule")


def _extract_overview(blocks: List[DocumentBlock], sections: Dict[str, List[str]]) -> Dict[str, Any]:
    summary_ids = set(sections.get("summary", []))
    summary_blocks = [block for block in blocks if block.block_id in summary_ids][:4]
    if summary_blocks:
        text = "\n".join(block.text for block in summary_blocks)
        return make_scored_value(value=text, confidence=0.72, evidence=build_evidence(summary_blocks), source="rule")
    return make_scored_value(value="", confidence=0.0, evidence={"block_ids": [], "text_snippets": [], "page_refs": []}, source="rule")


def _extract_location(blocks: List[DocumentBlock]) -> Dict[str, Any]:
    for block in blocks[:12]:
        text = _normalize_content_text(block.text)
        if any(token in text for token in ("上海", "北京", "深圳", "广州", "杭州", "美国", "中国", "location")):
            return make_scored_value(value=text, confidence=0.45, evidence=build_evidence([block]), source="rule")
    return make_scored_value(value="", confidence=0.0, evidence={"block_ids": [], "text_snippets": [], "page_refs": []}, source="rule")


def _extract_skill_tags(
    blocks: List[DocumentBlock],
    concepts: Dict[str, Dict[str, Any]],
    *,
    layout_lines: List[str] | None = None,
) -> Dict[str, Any]:
    raw_hits: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for concept_name, entry in concepts.items():
        aliases = [concept_name, *(entry.get("aliases", []) or [])]
        for block in blocks:
            lower = block.text.lower()
            if any(alias.lower() in lower for alias in aliases):
                if concept_name not in raw_hits:
                    raw_hits.append(concept_name)
                    normalized.append(make_scored_value(value=concept_name, confidence=0.82, evidence=build_evidence([block]), source="rule"))
                break
    for skill in _extract_layout_skill_items(layout_lines or []):
        if skill not in raw_hits:
            raw_hits.append(skill)
        matched_concept = _match_skill_concept(skill, concepts)
        if matched_concept and not any(str(item.get("value", "") or "") == matched_concept for item in normalized):
            normalized.append(make_scored_value(value=matched_concept, confidence=0.78, evidence={"block_ids": [], "text_snippets": [], "page_refs": []}, source="layout_rule"))
    return {
        "raw": raw_hits,
        "normalized": normalized,
    }


def _extract_layout_skill_items(layout_lines: List[str]) -> List[str]:
    lines = _section_lines(
        layout_lines,
        ("skills", "技能", "专业技能", "个人技能"),
        ("work experience", "experience", "education", "project", "personal project", "summary", "profile"),
    )
    skills: List[str] = []
    for line in lines:
        cleaned = _normalize_content_text(line).strip(" -|")
        if not cleaned or _is_contact_noise(cleaned) or _is_location_only_line(cleaned):
            continue
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1]
        elif "：" in cleaned:
            cleaned = cleaned.split("：", 1)[1]
        for item in re.split(r"[,，;/、]|\s{2,}", cleaned):
            skill = item.strip(" -|•")
            if not skill or len(skill) > 48:
                continue
            if _is_contact_noise(skill) or _is_location_only_line(skill):
                continue
            if skill.lower() in {"and", "&"}:
                continue
            if skill not in skills:
                skills.append(skill)
    return skills[:48]


def _match_skill_concept(skill: str, concepts: Dict[str, Dict[str, Any]]) -> str:
    normalized = _normalize_match_key(skill)
    for concept_name, entry in concepts.items():
        aliases = [concept_name, *(entry.get("aliases", []) or [])]
        if normalized in {_normalize_match_key(alias) for alias in aliases}:
            return concept_name
    return ""


def _extract_language_tags(blocks: List[DocumentBlock]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for block in blocks:
        text = block.text
        for token in ("英语", "中文", "English", "Japanese", "日语"):
            if token.lower() in text.lower():
                hits.append(make_scored_value(value=token, confidence=0.76, evidence=build_evidence([block]), source="rule"))
    return _dedupe_scored_values(hits)


def _extract_certifications(blocks: List[DocumentBlock]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for block in blocks:
        text = block.text
        if any(token in text for token in ("TOEFL", "GRE", "雅思", "PMP", "证书", "CFA")):
            hits.append(make_scored_value(value=text, confidence=0.7, evidence=build_evidence([block]), source="rule"))
    return hits[:8]


def _extract_portfolio_links(blocks: List[DocumentBlock]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for block in blocks:
        for url in URL_RE.findall(block.text):
            hits.append(make_scored_value(value=url, confidence=0.9, evidence=build_evidence([block]), source="rule"))
    return hits


def _extract_work_experiences(
    blocks: List[DocumentBlock],
    section_config: SectionAliasConfig,
    *,
    layout_lines: List[str] | None = None,
) -> List[Dict[str, Any]]:
    section_block_ids = _detect_section_block_ids(
        blocks=blocks,
        start_titles=section_config.work_sections,
        stop_titles=[
            *section_config.project_sections,
            *section_config.education_sections,
            *section_config.skill_sections,
            *section_config.summary_sections,
        ],
    )
    entries = _parse_resume_entries(blocks=blocks, section_block_ids=section_block_ids, entry_kind="work")
    entries = _merge_layout_work_entries(entries, _parse_layout_work_entries(layout_lines or []))
    entries = _attach_work_entry_block_evidence(entries, blocks=blocks, section_block_ids=section_block_ids)
    return _sort_temporal_entries(entries)


def _extract_education_experiences(
    blocks: List[DocumentBlock],
    section_config: SectionAliasConfig,
    *,
    layout_lines: List[str] | None = None,
) -> List[Dict[str, Any]]:
    section_block_ids = _detect_section_block_ids(
        blocks=blocks,
        start_titles=section_config.education_sections,
        stop_titles=[*section_config.project_sections, *section_config.work_sections, *section_config.skill_sections, *section_config.summary_sections],
    )
    entries = _parse_resume_entries(blocks=blocks, section_block_ids=section_block_ids, entry_kind="education")
    entries = _merge_layout_education_entries(entries, _parse_layout_education_entries(layout_lines or []))
    return _sort_temporal_entries(_dedupe_education_entries(entries))


def _detect_section_block_ids(
    *,
    blocks: List[DocumentBlock],
    start_titles: List[str],
    stop_titles: List[str],
) -> List[str]:
    start_index = -1
    end_index = len(blocks)
    normalized_start_titles = {_normalize_heading(item) for item in start_titles}
    normalized_stop_titles = {_normalize_heading(item) for item in stop_titles}
    for index, block in enumerate(blocks):
        if _normalize_heading(block.text) in normalized_start_titles:
            start_index = index
            break
    if start_index == -1:
        return []
    for index in range(start_index + 1, len(blocks)):
        if _normalize_heading(blocks[index].text) in normalized_stop_titles:
            end_index = index
            break
    return [block.block_id for block in blocks[start_index:end_index]]


def _extract_pdf_layout_lines(blocks: List[DocumentBlock]) -> List[str]:
    if not blocks:
        return []
    source_file = Path(blocks[0].source_file)
    if source_file.suffix.lower() != ".pdf" or not source_file.exists():
        return []
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(source_file), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return []
    return [
        unicodedata.normalize("NFKC", line).strip()
        for line in completed.stdout.replace("\r\n", "\n").split("\n")
        if line.strip()
    ]


def _section_lines(layout_lines: List[str], start_tokens: Tuple[str, ...], stop_tokens: Tuple[str, ...]) -> List[str]:
    start_index = -1
    end_index = len(layout_lines)
    for index, line in enumerate(layout_lines):
        normalized = _normalize_content_text(line).lower()
        if any(token.lower() in normalized for token in start_tokens):
            start_index = index
            break
    if start_index == -1:
        return []
    for index in range(start_index + 1, len(layout_lines)):
        normalized = _normalize_content_text(layout_lines[index]).lower()
        if any(token.lower() in normalized for token in stop_tokens):
            end_index = index
            break
    return layout_lines[start_index + 1 : end_index]


def _parse_layout_education_entries(layout_lines: List[str]) -> List[Dict[str, Any]]:
    lines = _section_lines(
        layout_lines,
        ("教育背景", "教育经历", "education"),
        ("工作经历", "工作经验", "work experience", "experience", "项目经历", "个人技能", "技能", "skills", "summary"),
    )
    entries: List[Dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = _normalize_content_text(lines[index])
        if not _looks_like_school_line(line):
            index += 1
            continue
        start_date, end_date = _extract_dates(line)
        school = _clean_layout_school_line(line)
        next_line = _normalize_content_text(lines[index + 1]) if index + 1 < len(lines) else ""
        degree = ""
        major = ""
        if next_line and not _looks_like_school_line(next_line) and _looks_like_degree_or_major_line(next_line):
            major, degree = _split_major_degree(next_line)
        if not major and not degree and _looks_like_degree_or_major_line(line):
            major, degree = _split_major_degree(line.replace(school, ""))
        if not (school and (start_date or end_date or major or degree)):
            index += 1
            continue
        entries.append(
            {
                "school_name": school,
                "degree": degree,
                "major": major,
                "start_date": start_date,
                "end_date": end_date,
                "rank_or_gpa": _extract_rank_or_gpa(next_line),
                "raw_line": " ".join([line, next_line]).strip(),
                "confidence": 0.82,
                "source": "layout_rule",
            }
        )
        index += 2 if next_line else 1
    return entries


def _parse_layout_work_entries(layout_lines: List[str]) -> List[Dict[str, Any]]:
    lines = _section_lines(
        layout_lines,
        ("工作经历", "工作经验", "work experience", "work history", "experience"),
        ("项目经历", "项目经验", "personal project", "projects", "education", "教育背景", "教育经历", "skills", "技能", "自我评价", "summary", "profile"),
    )
    entries: List[Dict[str, Any]] = []
    index = 0
    while index < len(lines):
        inline = _parse_layout_inline_work_line(_normalize_content_text(lines[index]))
        if inline:
            entries.append(inline)
            index += 1
            continue
        if index + 1 >= len(lines):
            break
        first_line = _normalize_content_text(lines[index])
        second_line = _normalize_content_text(lines[index + 1])
        first_start, first_end = _extract_dates(first_line)
        second_start, second_end = _extract_dates(second_line)
        if _looks_like_role_text(first_line) and (second_start or second_end):
            start_date, end_date = second_start, second_end
            title = _clean_heading_text(first_line)
            company_line = _strip_date_ranges(second_line).strip(" -|")
            location = _extract_location_from_line(company_line)
            company = company_line
            if location and company.endswith(location):
                company = company[: -len(location)].strip(" -|,")
            summary: List[str] = []
            cursor = index + 2
            while cursor < len(lines):
                current = _normalize_content_text(lines[cursor])
                following = _normalize_content_text(lines[cursor + 1]) if cursor + 1 < len(lines) else ""
                if _looks_like_role_text(current) and any(_extract_dates(following)):
                    break
                summary.append(current)
                cursor += 1
            entries.append(
                {
                    "company_name": company,
                    "job_title_raw": title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location,
                    "summary_raw": "\n".join(summary),
                    "raw_line": " ".join([first_line, second_line, *summary]).strip(),
                    "confidence": 0.86,
                    "source": "layout_rule",
                }
            )
            index = cursor
            continue
        if _looks_like_work_company_layout_line(first_line) and (second_start or second_end):
            start_date, end_date = second_start, second_end
            title = _strip_date_ranges(second_line).strip(" -|")
            location = _extract_location_from_line(first_line)
            company = first_line
            if location and company.endswith(location):
                company = company[: -len(location)].strip(" -|")
            summary: List[str] = []
            cursor = index + 2
            while cursor < len(lines):
                current = _normalize_content_text(lines[cursor])
                following = _normalize_content_text(lines[cursor + 1]) if cursor + 1 < len(lines) else ""
                if _looks_like_work_company_layout_line(current) and any(_extract_dates(following)):
                    break
                summary.append(current)
                cursor += 1
            entries.append(
                {
                    "company_name": company,
                    "job_title_raw": title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location,
                    "summary_raw": "\n".join(summary),
                    "raw_line": " ".join([first_line, second_line, *summary]).strip(),
                    "confidence": 0.84,
                    "source": "layout_rule",
                }
            )
            index = cursor
            continue
        index += 1
    return entries


def _parse_layout_project_entries(layout_lines: List[str]) -> List[Dict[str, str]]:
    lines = _section_lines(layout_lines, ("项目经历", "科研经历", "科研项目", "研究经历", "project", "research"), ("个人技能", "技能", "自我评价", "作品集", "获奖证书"))
    entries: List[Dict[str, str]] = []
    for line in lines:
        normalized = _normalize_content_text(line)
        if not DATE_RANGE_RE.search(normalized) or normalized.startswith(("-", "•", "*")):
            continue
        start_date, end_date = _extract_dates(normalized)
        title_part = DATE_RANGE_RE.split(normalized)[0].strip()
        if not title_part:
            continue
        parts = re.split(r"\s{2,}", title_part)
        title = parts[0].strip()
        organization = parts[1].strip() if len(parts) > 1 else ""
        if title and _looks_like_project_title(title):
            entries.append(
                {
                    "title": title,
                    "organization_raw": organization,
                    "date_range_raw": DATE_RANGE_RE.search(normalized).group(0),
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
    return entries


def _apply_layout_project_dates(candidates: List[Dict[str, Any]], layout_lines: List[str]) -> List[Dict[str, Any]]:
    layout_projects = _parse_layout_project_entries(layout_lines)
    if not layout_projects:
        return candidates
    updated = [dict(item) for item in candidates]
    for item in updated:
        if str(item.get("date_range_raw", "")).strip():
            continue
        title = _normalize_match_key(str(item.get("chunk_title", "")))
        matched = next(
            (
                project
                for project in layout_projects
                if title and (title in _normalize_match_key(project["title"]) or _normalize_match_key(project["title"]) in title)
            ),
            None,
        )
        if not matched:
            continue
        item["date_range_raw"] = matched["date_range_raw"]
        if not str(item.get("organization_raw", "")).strip() and matched.get("organization_raw"):
            item["organization_raw"] = matched["organization_raw"]
    return _sort_project_candidates(updated)


def _sort_project_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(item: Dict[str, Any]) -> Tuple[int, str]:
        start, end = _extract_dates(str(item.get("date_range_raw", "") or ""))
        marker = {"start_date": start, "end_date": end}
        temporal = _temporal_sort_key(marker)
        return temporal[0], temporal[1] or temporal[2]

    dated = [item for item in candidates if key(item)[0] == 0]
    dated.sort(key=lambda item: key(item)[1], reverse=True)
    undated = [item for item in candidates if key(item)[0] == 1]
    return dated + undated


def _parse_resume_entries(
    *,
    blocks: List[DocumentBlock],
    section_block_ids: List[str],
    entry_kind: str,
) -> List[Dict[str, Any]]:
    if not section_block_ids:
        return []
    block_map = {block.block_id: block for block in blocks}
    section_blocks = [block_map[block_id] for block_id in section_block_ids if block_id in block_map]
    if len(section_blocks) <= 1:
        return []
    content_blocks = section_blocks[1:]
    entries: List[List[DocumentBlock]] = []
    current: List[DocumentBlock] = []
    for block in content_blocks:
        text = _normalize_content_text(block.text)
        if not text:
            continue
        if current and _should_split_resume_entry(current=current, next_text=text, entry_kind=entry_kind):
            entries.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        entries.append(current)
    parsed_entries = [_build_resume_entry_payload(item, entry_kind=entry_kind, ordinal=index + 1) for index, item in enumerate(entries) if item]
    return [item for item in parsed_entries if _is_valid_resume_entry(item, entry_kind=entry_kind)]


def _should_split_resume_entry(*, current: List[DocumentBlock], next_text: str, entry_kind: str) -> bool:
    if entry_kind == "education":
        return _looks_like_resume_entry_start(next_text, entry_kind=entry_kind)
    if not current:
        return False
    current_text = _normalize_content_text(current[0].text)
    if entry_kind == "work" and _parse_inline_work_entry(current_text) is not None and _parse_inline_work_entry(next_text) is not None:
        return True
    if entry_kind == "work" and len(current) >= 2 and _is_date_only_line(next_text):
        return False
    if len(current) == 1 and (_looks_like_date_or_title_line(next_text) or _looks_like_work_header_line(next_text)):
        return False
    if len(current) >= 2 and _looks_like_work_header_line(next_text):
        return True
    if len(current) >= 2 and _looks_like_resume_entry_start(next_text, entry_kind=entry_kind):
        return True
    return False


def _looks_like_resume_entry_start(text: str, *, entry_kind: str) -> bool:
    normalized = _normalize_content_text(text)
    if not normalized:
        return False
    if entry_kind == "education" and any(token in normalized.lower() for token in ("university", "college", "school")):
        return True
    if entry_kind == "education":
        return False
    if normalized.startswith(("-", "•", "*")) or _looks_like_work_detail_line(normalized):
        return False
    if re.search(r"\d{4}[./-]\d{1,2}\s*(?:至|到|-|–|—)", normalized):
        return True
    if entry_kind == "work" and len(normalized) <= 50 and not re.search(r"[。；;]", normalized):
        return True
    return False


def _build_resume_entry_payload(entry_blocks: List[DocumentBlock], *, entry_kind: str, ordinal: int) -> Dict[str, Any]:
    texts = [_normalize_content_text(block.text) for block in entry_blocks if _normalize_content_text(block.text)]
    combined = " ".join(texts)
    start_date, end_date = _extract_dates(combined)
    evidence = build_evidence(entry_blocks)
    evidence_ids = list(evidence.get("block_ids", []) or [])
    first_line = texts[0] if texts else ""
    second_line = texts[1] if len(texts) > 1 else ""
    summary_lines = _extract_entry_summary_lines(texts, entry_kind=entry_kind)
    if entry_kind == "work":
        inline_entry = _parse_inline_work_entry(first_line)
        if inline_entry is not None:
            return {
                "work_ref": f"work_{ordinal}",
                "company_name": inline_entry["company_name"],
                "job_title_raw": inline_entry["job_title_raw"],
                "start_date": inline_entry["start_date"],
                "end_date": inline_entry["end_date"],
                "location": inline_entry["location"],
                "summary_raw": "\n".join(summary_lines),
                "raw_line": combined,
                "confidence": 0.82,
                "evidence": evidence,
                "source": "rule",
            }
        if (start_date or end_date) and _looks_like_role_text(second_line):
            company = _strip_date_ranges(first_line).strip(" -|")
            location = _extract_location_from_line(second_line)
            title = second_line[: -len(location)].strip(" -|,") if location and second_line.endswith(location) else second_line
            return {
                "work_ref": f"work_{ordinal}",
                "company_name": _clean_heading_text(company),
                "job_title_raw": _clean_heading_text(title),
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "summary_raw": "\n".join(texts[2:]),
                "raw_line": combined,
                "confidence": 0.84,
                "evidence": evidence,
                "source": "rule",
            }
        if len(texts) >= 3 and _is_date_only_line(second_line) and _looks_like_role_text(texts[2]):
            location = _extract_location_from_line(texts[2])
            title = texts[2][: -len(location)].strip(" -|,") if location and texts[2].endswith(location) else texts[2]
            return {
                "work_ref": f"work_{ordinal}",
                "company_name": _clean_heading_text(first_line),
                "job_title_raw": _clean_heading_text(title),
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "summary_raw": "\n".join(texts[3:]),
                "raw_line": combined,
                "confidence": 0.84,
                "evidence": evidence,
                "source": "rule",
            }
        return {
            "work_ref": f"work_{ordinal}",
            "company_name": _clean_heading_text(first_line),
            "job_title_raw": _clean_heading_text(second_line),
            "start_date": start_date,
            "end_date": end_date,
            "location": _extract_location_from_line(first_line),
            "summary_raw": "\n".join(summary_lines),
            "raw_line": combined,
            "confidence": 0.8 if evidence_ids else 0.0,
            "evidence": evidence,
            "source": "rule",
        }
    degree_line = first_line if _looks_like_degree_or_major_line(first_line) else second_line
    if _is_date_only_line(degree_line):
        degree_line = ""
    school_line = second_line if degree_line == first_line else first_line
    major, degree = _split_major_degree(degree_line)
    return {
        "school_name": _clean_heading_text(school_line),
        "degree": degree,
        "major": major,
        "start_date": start_date,
        "end_date": end_date,
        "rank_or_gpa": _extract_rank_or_gpa("\n".join(texts)),
        "raw_line": combined,
        "confidence": 0.76 if evidence_ids else 0.0,
        "evidence": evidence,
        "source": "rule",
    }


def _is_valid_resume_entry(item: Dict[str, Any], *, entry_kind: str) -> bool:
    if entry_kind == "work":
        company = str(item.get("company_name", "")).strip()
        title = str(item.get("job_title_raw", "")).strip()
        summary = str(item.get("summary_raw", "") or "").strip()
        raw_line = str(item.get("raw_line", "") or "").strip()
        if (
            _is_resume_entry_noise(company)
            or _is_resume_entry_noise(title)
            or _is_contact_noise(raw_line)
            or (_is_section_heading(company) and not (item.get("start_date") or item.get("end_date")))
        ):
            return False
        if not (item.get("start_date") or item.get("end_date")) and not any(
            token in " ".join([company, title, summary])
            for token in ("公司", "集团", "科技", "Software", "Engineer", "Developer", "Intern", "工程师", "开发")
        ):
            return False
        return bool(company and (title or item.get("summary_raw")))
    school = str(item.get("school_name", "")).strip()
    has_school_signal = any(token in school.lower() for token in ("university", "college", "school")) or any(
        token in school for token in ("大学", "学院", "学校")
    )
    return bool(has_school_signal or (item.get("start_date") and item.get("end_date")))


def _is_resume_entry_noise(text: str) -> bool:
    cleaned = _clean_heading_text(text)
    if not cleaned:
        return True
    if _is_section_heading(cleaned) or _is_contact_noise(cleaned) or _is_location_only_line(cleaned) or _is_date_only_line(cleaned):
        return True
    return False


def _is_contact_noise(text: str) -> bool:
    cleaned = _normalize_content_text(text)
    if not cleaned:
        return False
    if EMAIL_RE.search(cleaned) or URL_RE.search(cleaned) or WECHAT_RE.search(cleaned):
        return True
    if re.search(r"\+?\d[\d\s().-]{7,}\d", cleaned):
        return True
    return False


def _is_location_only_line(text: str) -> bool:
    cleaned = _clean_heading_text(text).strip(" ,")
    if not cleaned or len(cleaned) > 48:
        return False
    city_tokens = (
        "Houston", "Shanghai", "San Diego", "Beijing", "Shenzhen", "Hangzhou",
        "Texas", "China", "CA", "TX", "北京", "上海", "深圳", "杭州", "广州",
    )
    if not any(token.lower() in cleaned.lower() for token in city_tokens):
        return False
    residue = re.sub(r"\b(?:Houston|Shanghai|San Diego|Beijing|Shenzhen|Hangzhou|Texas|China|CA|TX)\b", "", cleaned, flags=re.IGNORECASE)
    residue = re.sub(r"(北京|上海|深圳|杭州|广州|中国|美国)", "", residue)
    residue = re.sub(r"[\s,，/-]+", "", residue)
    return residue == ""


def _merge_layout_education_entries(existing: List[Dict[str, Any]], layout_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not layout_entries:
        return existing
    if not existing or _entries_look_suspicious(existing, kind="education"):
        return _with_default_evidence(layout_entries)
    merged = [dict(item) for item in existing]
    matched_indexes: set[int] = set()
    for item in merged:
        school = _normalize_match_key(str(item.get("school_name", "")))
        match_index = next(
            (
                index
                for index, candidate in enumerate(layout_entries)
                if index not in matched_indexes and school and school in _normalize_match_key(str(candidate.get("school_name", "")))
            ),
            -1,
        )
        if match_index == -1:
            continue
        matched_indexes.add(match_index)
        candidate = layout_entries[match_index]
        for field in ("degree", "major", "start_date", "end_date", "rank_or_gpa", "raw_line"):
            if not str(item.get(field, "")).strip() and str(candidate.get(field, "")).strip():
                item[field] = candidate[field]
        item["source"] = "rule+layout" if item.get("source") else "layout_rule"
    for index, candidate in enumerate(layout_entries):
        if index not in matched_indexes and _is_valid_resume_entry(candidate, entry_kind="education"):
            payload = dict(candidate)
            payload.setdefault("evidence", {"block_ids": [], "text_snippets": [], "page_refs": []})
            merged.append(payload)
    return merged


def _dedupe_education_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for item in entries:
        payload = dict(item)
        school = _clean_layout_school_line(str(payload.get("school_name", "") or ""))
        payload["school_name"] = school
        key = (
            _normalize_match_key(school),
            _normalize_sort_date(str(payload.get("start_date", "") or "")),
            _normalize_sort_date(str(payload.get("end_date", "") or "")),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(payload)
    return output


def _merge_layout_work_entries(existing: List[Dict[str, Any]], layout_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not layout_entries:
        return existing
    if not existing or _entries_look_suspicious(existing, kind="work"):
        return [
            {**item, "work_ref": f"work_{index + 1}", "evidence": {"block_ids": [], "text_snippets": [], "page_refs": []}}
            for index, item in enumerate(_sort_temporal_entries(layout_entries))
        ]
    merged = [dict(item) for item in existing]
    matched_indexes: set[int] = set()
    for item in merged:
        company = _normalize_match_key(str(item.get("company_name", "")))
        match_index = next(
            (
                index
                for index, candidate in enumerate(layout_entries)
                if index not in matched_indexes and company and company in _normalize_match_key(str(candidate.get("company_name", "")))
            ),
            -1,
        )
        if match_index == -1:
            continue
        matched_indexes.add(match_index)
        candidate = layout_entries[match_index]
        for field in ("job_title_raw", "start_date", "end_date", "location"):
            if not str(item.get(field, "")).strip() and str(candidate.get(field, "")).strip():
                item[field] = candidate[field]
        item["source"] = "rule+layout" if item.get("source") else "layout_rule"
    next_ref = len(merged) + 1
    for index, candidate in enumerate(layout_entries):
        if index in matched_indexes or not _is_valid_resume_entry(candidate, entry_kind="work"):
            continue
        payload = dict(candidate)
        payload["work_ref"] = f"work_{next_ref}"
        payload.setdefault("evidence", {"block_ids": [], "text_snippets": [], "page_refs": []})
        merged.append(payload)
        next_ref += 1
    return merged


def _attach_work_entry_block_evidence(
    entries: List[Dict[str, Any]],
    *,
    blocks: List[DocumentBlock],
    section_block_ids: List[str],
) -> List[Dict[str, Any]]:
    if not entries or not section_block_ids:
        return entries
    block_map = {block.block_id: block for block in blocks}
    work_blocks = [block_map[block_id] for block_id in section_block_ids if block_id in block_map]
    if not work_blocks:
        return entries
    output: List[Dict[str, Any]] = []
    used_ids: set[str] = set()
    for entry in entries:
        existing_ids = [str(item).strip() for item in list(dict(entry.get("evidence", {}) or {}).get("block_ids", []) or []) if str(item).strip()]
        if existing_ids:
            output.append(entry)
            used_ids.update(existing_ids)
            continue
        matched = _match_work_entry_blocks(entry, work_blocks=work_blocks, used_ids=used_ids)
        payload = dict(entry)
        if matched:
            payload["evidence"] = build_evidence(matched)
            used_ids.update(block.block_id for block in matched)
            if not str(payload.get("source", "") or "").strip():
                payload["source"] = "layout_rule"
        output.append(payload)
    return output


def _match_work_entry_blocks(entry: Dict[str, Any], *, work_blocks: List[DocumentBlock], used_ids: set[str]) -> List[DocumentBlock]:
    raw_line = _normalize_for_substring_match(str(entry.get("raw_line", "") or ""))
    summary = _normalize_for_substring_match(str(entry.get("summary_raw", "") or ""))
    company = _normalize_for_substring_match(str(entry.get("company_name", "") or ""))
    title = _normalize_for_substring_match(str(entry.get("job_title_raw", "") or ""))
    date_text = _normalize_for_substring_match(" ".join([str(entry.get("start_date", "") or ""), str(entry.get("end_date", "") or "")]))
    matched: List[DocumentBlock] = []
    in_entry = False
    for block in work_blocks:
        text = _normalize_content_text(block.text)
        key = _normalize_for_substring_match(text)
        if not key or block.block_id in used_ids:
            continue
        is_header = (
            (company and company in key)
            or (title and title in key)
            or (date_text and date_text in key)
            or (company and company in raw_line and key in raw_line)
        )
        is_body = bool((raw_line and key in raw_line) or (summary and key in summary))
        if is_header:
            in_entry = True
            matched.append(block)
            continue
        if in_entry and is_body:
            matched.append(block)
            continue
        if in_entry and _looks_like_work_header_line(text):
            break
    return matched


def _normalize_for_substring_match(value: str) -> str:
    normalized = _normalize_content_text(value).lower()
    normalized = re.sub(r"[\s#|｜,，.。;；:：()（）/\\-]+", "", normalized)
    return normalized


def _with_default_evidence(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {**item, "evidence": item.get("evidence") or {"block_ids": [], "text_snippets": [], "page_refs": []}}
        for item in entries
    ]


def _entries_look_suspicious(entries: List[Dict[str, Any]], *, kind: str) -> bool:
    if kind == "work":
        suspicious = 0
        for item in entries:
            company = str(item.get("company_name", "") or "")
            title = str(item.get("job_title_raw", "") or "")
            company_is_role = _looks_like_role_text(company) and not _looks_like_work_company_layout_line(company)
            title_is_detail = title.startswith(("-", "•", "*")) or _looks_like_work_detail_line(title)
            if (
                _extract_dates(company) != ("", "")
                or _extract_dates(title) != ("", "")
                or _is_date_only_repair_noise(company)
                or company_is_role
                or title_is_detail
                or not str(item.get("start_date", "") or "").strip()
            ):
                suspicious += 1
        return suspicious >= max(1, len(entries) // 2)
    suspicious = 0
    for item in entries:
        school = str(item.get("school_name", "") or "")
        major = str(item.get("major", "") or "")
        if not _looks_like_school_line(school) or ("个人总结" in major):
            suspicious += 1
    return suspicious >= max(1, len(entries) // 2)


def _clean_heading_text(text: str) -> str:
    return _normalize_content_text(text).lstrip("#").strip()


def _looks_like_degree_or_major_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    degree_tokens = ("本科", "硕士", "博士", "Master", "Bachelor", "PhD", "B.S.", "M.S.", "BS", "MS")
    major_tokens = ("Computer Science", "计算机", "软件工程", "Science", "Engineering")
    return any(token.lower() in normalized.lower() for token in degree_tokens + major_tokens)


def _split_major_degree(text: str) -> Tuple[str, str]:
    cleaned = _clean_heading_text(DATE_RANGE_RE.sub("", text))
    cleaned = re.sub(r"(成绩排名|GPA|Rank)[:：]?.*$", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return "", ""
    parts = [item.strip(" -|｜•") for item in re.split(r"\s*[|｜•]\s*|\s{2,}", cleaned) if item.strip(" -|｜•")]
    degree_tokens = ("本科", "硕士", "博士", "Master", "Bachelor", "PhD", "B.S.", "M.S.", "BS", "MS")
    degree = ""
    major_parts: List[str] = []
    for part in parts or [cleaned]:
        token = _extract_degree_token(part)
        if token:
            degree = token
        elif _looks_like_major_text(part):
            major_parts.append(part)
    if not degree:
        degree = _extract_degree_token(cleaned)
    major = " ".join(major_parts).strip()
    if major == degree:
        major = ""
    return major, degree


def _extract_degree_token(text: str) -> str:
    normalized = _normalize_content_text(text)
    degree_patterns = (
        r"本科",
        r"硕士",
        r"博士",
        r"PhD",
        r"Master(?:'s)?(?:\s+Degree)?",
        r"Bachelor(?:'s)?(?:\s+Degree)?",
        r"\bM\.?S\.?\b",
        r"\bB\.?S\.?\b",
        r"\bMS\b",
        r"\bBS\b",
    )
    for pattern in degree_patterns:
        matched = re.search(pattern, normalized, flags=re.IGNORECASE)
        if matched:
            return matched.group(0).strip()
    return ""


def _looks_like_major_text(text: str) -> bool:
    normalized = _normalize_content_text(text)
    if not normalized or DATE_RANGE_RE.search(normalized):
        return False
    if any(token in normalized for token in ("word", "excel", "ppt", "主修课程", "掌握", "负责", "熟悉")):
        return False
    return any(
        token.lower() in normalized.lower()
        for token in (
            "Computer Science",
            "Software Engineering",
            "Data Science",
            "Information",
            "Engineering",
            "计算机",
            "软件工程",
            "生物信息",
            "信息工程",
            "数据科学",
        )
    )


def _extract_entry_summary_lines(texts: List[str], *, entry_kind: str) -> List[str]:
    if not texts:
        return []
    if entry_kind != "work":
        return texts[2:] if len(texts) > 2 else []
    if len(texts) <= 2:
        return []
    summary_start = 2
    for index, text in enumerate(texts[2:], start=2):
        if _looks_like_work_detail_line(text):
            summary_start = index
            break
    return texts[summary_start:]


def _looks_like_work_detail_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    detail_markers = ("负责", "参与", "推动", "设计", "开发", "实现", "构建", "搭建", "优化", "使用", "支持")
    return any(marker in normalized for marker in detail_markers) or bool(re.search(r"[。；;]|,|，", normalized))


def _looks_like_work_header_line(text: str) -> bool:
    raw = _normalize_content_text(text)
    normalized = _clean_heading_text(raw)
    if not normalized or len(normalized) > 80:
        return False
    if _is_section_heading(normalized) or _is_contact_noise(normalized) or _is_location_only_line(normalized):
        return False
    if any(token in normalized.lower() for token in ("university", "college")):
        return False
    if any(token in normalized for token in ("有限公司", "公司", "集团", "科技", "软件", "银行", "大学", "研究院")):
        return True
    if raw.startswith("#") and re.search(r"[A-Za-z]", normalized):
        return True
    return bool(re.search(r"[A-Za-z].*(Software|Inc|LLC|Technolog|Huawei|Matrix)", normalized, flags=re.IGNORECASE))


def _looks_like_date_or_title_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    return bool(re.search(r"\d{4}[./-]\d{1,2}\s*(?:至|到|-|–|—)", normalized)) or any(
        token in normalized for token in ("工程师", "开发", "Developer", "Engineer")
    )


def _is_date_only_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    if not normalized:
        return False
    without_date = DATE_RANGE_RE.sub("", MONTH_DATE_RANGE_RE.sub("", MONTH_TO_PRESENT_RE.sub("", normalized)))
    return not re.sub(
        r"[\s./\-–—至到~年月今presentcurrentjanfebmaraprmayjunjulaugseptoctnovdec]+",
        "",
        without_date,
        flags=re.IGNORECASE,
    )


def _extract_location_from_line(text: str) -> str:
    parts = [item.strip() for item in re.split(r"\s{2,}|[|｜]", text) if item.strip()]
    if len(parts) >= 2:
        return parts[-1]
    matched = re.search(
        r"((?:北京|上海|深圳|杭州|广州|成都|苏州|南京|武汉|西安|长沙|青岛|天津|重庆|郑州|合肥|厦门|宁波|无锡|佛山|东莞|香港|澳门|台北|美国|英国|新加坡|日本|韩国|德国|法国|加拿大|澳大利亚|休斯顿)(?:\s+(?:美国|英国|新加坡|日本|韩国|德国|法国|加拿大|澳大利亚))?)$",
        text.strip(),
    )
    return matched.group(1).strip() if matched else ""


def _parse_inline_work_entry(text: str) -> Dict[str, str] | None:
    normalized = _normalize_content_text(text)
    matched = re.match(
        r"^(?P<start>\d{4}[./-]\d{1,2})\s*[-–—至到]+\s*(?P<end>\d{4}[./-]\d{1,2}|至今|Present)\s+(?P<tail>.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if not matched:
        return None
    tail = matched.group("tail").strip()
    tokens = tail.split()
    if len(tokens) < 2:
        return None
    return {
        "company_name": " ".join(tokens[:-1]).strip(),
        "job_title_raw": tokens[-1].strip(),
        "start_date": matched.group("start").strip(),
        "end_date": matched.group("end").strip(),
        "location": _extract_location_from_line(" ".join(tokens[:-1]).strip()),
    }


def _parse_layout_inline_work_line(text: str) -> Dict[str, Any] | None:
    normalized = _normalize_content_text(text)
    match = DATE_RANGE_RE.search(normalized)
    if not match or normalized.startswith(("-", "•", "*")):
        return None
    start_date, end_date = _extract_dates(normalized)
    before = normalized[: match.start()].strip(" -|•")
    after = normalized[match.end() :].strip(" -|•")
    company = ""
    title = ""
    location = ""
    if before and after:
        title = before
        company = after
    elif after:
        parts = [item.strip() for item in re.split(r"\s{2,}", after) if item.strip()]
        if len(parts) >= 2:
            company, title = parts[0], parts[1]
        else:
            loose = after.split()
            if len(loose) >= 2:
                company, title = loose[0], " ".join(loose[1:])
    elif before:
        parts = [item.strip() for item in re.split(r"\s*[•|｜]\s*|\s{2,}", before) if item.strip()]
        if len(parts) >= 3 and _looks_like_role_text(parts[-2]) and not _looks_like_role_text(parts[-1]):
            title, company = _extract_role_substring(parts[-2]), parts[-1]
        elif len(parts) >= 2 and _looks_like_role_text(parts[-1]):
            split_entry = _split_company_title_by_role(parts[-1])
            if split_entry:
                company, title = split_entry
            elif _looks_like_role_text(parts[-2]):
                title, company = _extract_role_substring(parts[-2]), parts[-1]
        elif len(parts) >= 2:
            if _looks_like_role_text(parts[0]) and not _looks_like_role_text(parts[1]):
                title, company = _extract_role_substring(parts[0]), parts[1]
            else:
                company, title = parts[0], parts[1]
        else:
            split_entry = _split_company_title_by_role(before)
            if split_entry:
                company, title = split_entry
    location = _extract_location_from_line(company)
    if location and company.endswith(location):
        company = company[: -len(location)].strip(" -|")
    title = _extract_role_substring(title)
    if not (company and title and _looks_like_role_text(title)):
        return None
    return {
        "company_name": company,
        "job_title_raw": title,
        "start_date": start_date,
        "end_date": end_date,
        "location": location,
        "summary_raw": "",
        "raw_line": normalized,
        "confidence": 0.84,
        "source": "layout_rule",
    }


def _looks_like_role_text(text: str) -> bool:
    lowered = _normalize_content_text(text).lower()
    return any(token in text for token in ("工程师", "开发", "经理", "业务", "算法", "后端", "前端", "全栈")) or any(
        token in lowered for token in ("developer", "engineer", "intern")
    )


def _extract_role_substring(text: str) -> str:
    normalized = _normalize_content_text(text).strip(" -|•")
    role_patterns = (
        r"(?:后端|前端|全栈|算法|软件|生物信息|数据|测试|业务|产品|项目)?\s*(?:开发)?\s*(?:工程师|开发|经理)",
        r"(?:Full\s+Stack\s+)?Developer(?:[-\w\s.]*)?",
        r"(?:Software|Backend|Frontend|Full\s+Stack|Data|Algorithm)\s+Engineer(?:[-\w\s.]*)?",
    )
    best = ""
    for pattern in role_patterns:
        for matched in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            candidate = normalized[matched.start() :].strip(" -|•")
            if len(candidate) > len(best):
                best = candidate
    return best or normalized


def _split_company_title_by_role(text: str) -> Tuple[str, str] | None:
    normalized = _normalize_content_text(text).strip(" -|•")
    role_patterns = (
        r"(?:后端|前端|全栈|算法|软件|生物信息|数据|测试|业务|产品|项目)?\s*(?:开发)?\s*(?:工程师|开发|经理)",
        r"(?:Full\s+Stack\s+)?Developer",
        r"(?:Software|Backend|Frontend|Full\s+Stack|Data|Algorithm)\s+Engineer",
    )
    matches = [
        matched
        for pattern in role_patterns
        for matched in re.finditer(pattern, normalized, flags=re.IGNORECASE)
    ]
    if not matches:
        return None
    first = min(matches, key=lambda matched: matched.start())
    company = normalized[: first.start()].strip(" -|•")
    title = normalized[first.start() :].strip(" -|•")
    if not company or not title:
        return None
    return company, title


def _looks_like_school_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    return any(token in normalized.lower() for token in ("university", "college", "school")) or any(
        token in normalized for token in ("大学", "学院", "学校")
    )


def _clean_layout_school_line(text: str) -> str:
    cleaned = DATE_RANGE_RE.sub("", _normalize_content_text(text)).strip(" -|")
    parts = [item.strip(" -|•") for item in re.split(r"\s*[•|｜]\s*|\s{2,}", cleaned) if item.strip(" -|•")]
    for part in parts:
        if _looks_like_school_line(part):
            return part
    return cleaned


def _looks_like_work_company_layout_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    if not normalized or DATE_RANGE_RE.search(normalized):
        return False
    if normalized.startswith(("-", "•", "*")) or _looks_like_degree_or_major_line(normalized):
        return False
    if _looks_like_school_line(normalized):
        return False
    if any(token in normalized for token in ("有限公司", "公司", "集团", "科技", "软件", "银行", "研究院")):
        return True
    return bool(re.search(r"\b(Huawei|Matrix|Software|Inc|LLC|Technolog|Corporation|Group)\b", normalized, flags=re.IGNORECASE))


def _normalize_match_key(value: str) -> str:
    return re.sub(r"\s+", "", _normalize_content_text(value)).lower()


def _temporal_sort_key(item: Dict[str, Any]) -> Tuple[int, str, str]:
    end_date = str(item.get("end_date", "") or "")
    start_date = str(item.get("start_date", "") or "")
    if re.search(r"至今|present|current", end_date, flags=re.IGNORECASE):
        return (0, "9999-99", start_date)
    comparable = _normalize_sort_date(end_date or start_date)
    if not comparable:
        return (1, "", "")
    return (0, comparable, _normalize_sort_date(start_date))


def _normalize_sort_date(value: str) -> str:
    matched = re.search(r"((?:19|20)\d{2})[./-]?(\d{0,2})", value)
    if not matched:
        return ""
    month = matched.group(2) or "00"
    return f"{matched.group(1)}-{month.zfill(2)}"


def _sort_temporal_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dated = [item for item in entries if _temporal_sort_key(item)[0] == 0]
    dated.sort(key=lambda item: (_temporal_sort_key(item)[1], _temporal_sort_key(item)[2]), reverse=True)
    undated = [item for item in entries if _temporal_sort_key(item)[0] == 1]
    return dated + undated


def _extract_rank_or_gpa(text: str) -> str:
    matched = re.search(r"(前\d+%|GPA[:：]?\s*[0-9.]+)", text, flags=re.IGNORECASE)
    return matched.group(1).strip() if matched else ""


def _extract_concept_and_domain_tags(
    blocks: List[DocumentBlock],
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    concept_tags: List[Dict[str, Any]] = []
    for concept_name, entry in concepts.items():
        aliases = [concept_name, *(entry.get("aliases", []) or [])]
        for block in blocks:
            if any(alias.lower() in block.text.lower() for alias in aliases):
                concept_tags.append(make_scored_value(value=concept_name, confidence=0.78, evidence=build_evidence([block]), source="rule"))
                break
    domain_tags: List[Dict[str, Any]] = []
    for domain in domains.values():
        aliases = [domain.domain_name, *domain.aliases, *domain.search_hints]
        for block in blocks:
            if any(alias.lower() in block.text.lower() for alias in aliases):
                domain_tags.append(make_scored_value(value=domain.domain_name, confidence=0.72, evidence=build_evidence([block]), source="rule"))
                break
    return _dedupe_scored_values(concept_tags), _dedupe_scored_values(domain_tags)


def _extract_experience_tags(*, work_experiences: List[Dict[str, Any]], domain_tags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    total_months = 0
    role_months: Dict[str, int] = {}
    evidence_blocks: List[str] = []
    dated_work_count = 0
    for item in work_experiences:
        months = _work_duration_months(str(item.get("start_date", "") or ""), str(item.get("end_date", "") or ""))
        if months <= 0:
            continue
        dated_work_count += 1
        total_months += months
        evidence_blocks.extend(str(block_id) for block_id in list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []) if str(block_id))
        role_bucket = _experience_role_bucket(item)
        if role_bucket:
            role_months[role_bucket] = role_months.get(role_bucket, 0) + months
    tags: List[Dict[str, Any]] = []
    confidence = _experience_rule_confidence(
        work_count=len(work_experiences),
        dated_work_count=dated_work_count,
        evidence_blocks=evidence_blocks,
    )
    if total_months > 0:
        tags.append(_experience_tag("计算机经验", total_months, evidence_blocks, confidence=confidence))
    for bucket, months in sorted(role_months.items(), key=lambda pair: pair[1], reverse=True):
        if months >= 6:
            tags.append(_experience_tag(f"{bucket}经验", months, evidence_blocks, confidence=confidence))
    for domain_tag in domain_tags:
        value = str(domain_tag.get("value", "") or "").strip()
        if value and total_months >= 6:
            tags.append(
                _experience_tag(
                    f"{value}经验",
                    total_months,
                    list(dict(domain_tag.get("evidence", {}) or {}).get("block_ids", []) or evidence_blocks),
                    confidence=min(confidence, 0.82),
                )
            )
    return _dedupe_scored_values(tags)


def _experience_role_bucket(item: Dict[str, Any]) -> str:
    text = " ".join(
        str(item.get(field_name, "") or "")
        for field_name in ("company_name", "job_title_raw", "summary_raw", "raw_line")
    )
    lowered = text.lower()
    if any(token in text for token in ("算法", "推荐", "搜索", "模型", "数据挖掘", "机器学习")):
        return "算法"
    if any(token in lowered for token in ("backend", "full stack", "developer", "engineer")) or any(token in text for token in ("后端", "全栈", "软件", "开发", "Java", "Go", "Golang")):
        return "软件工程"
    if any(token in text for token in ("数据", "分析", "数仓", "ETL")):
        return "数据"
    return ""


def _experience_rule_confidence(*, work_count: int, dated_work_count: int, evidence_blocks: List[str]) -> float:
    if work_count <= 0 or dated_work_count <= 0:
        return 0.0
    coverage = dated_work_count / max(1, work_count)
    if coverage >= 0.85:
        return 0.88 if evidence_blocks else 0.84
    if coverage >= 0.5:
        return 0.74 if evidence_blocks else 0.68
    return 0.62


def _experience_tag(prefix: str, months: int, evidence_blocks: List[str], *, confidence: float) -> Dict[str, Any]:
    years = max(1, round(months / 12))
    return make_scored_value(
        value=f"{prefix}{years}年",
        confidence=confidence,
        evidence={"block_ids": _dedupe_strings(evidence_blocks), "text_snippets": [], "page_refs": []},
        source="rule_experience",
    )


def _work_duration_months(start_date: str, end_date: str) -> int:
    start = _parse_year_month(start_date)
    end = _parse_year_month(end_date)
    if not start:
        return 0
    if not end:
        if re.search(r"至今|present|current", end_date, flags=re.IGNORECASE):
            today = date.today()
            end = (today.year, today.month)
        else:
            return 0
    months = (end[0] - start[0]) * 12 + (end[1] - start[1]) + 1
    return max(0, months)


def _parse_year_month(value: str) -> Tuple[int, int] | None:
    if re.search(r"至今|present|current", value or "", flags=re.IGNORECASE):
        today = date.today()
        return today.year, today.month
    matched = re.search(r"((?:19|20)\d{2})[./-]?(\d{0,2})", value or "")
    if not matched:
        return None
    month = int(matched.group(2) or "1")
    month = min(max(month, 1), 12)
    return int(matched.group(1)), month


def _dedupe_strings(values: List[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def _string_list_from_config(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _build_chunk_candidates(
    blocks: List[DocumentBlock],
    sections: Dict[str, List[str]],
    chunking_config: ChunkingConfig,
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
    work_experiences: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    section_lookup = {block_id: section_name for section_name, block_ids in sections.items() for block_id in block_ids}
    results: List[Dict[str, Any]] = []
    used_block_ids = set()
    for work_item in list(work_experiences or []):
        evidence_ids = list(dict(work_item.get("evidence", {}) or {}).get("block_ids", []) or [])
        group = [block for block in blocks if block.block_id in set(evidence_ids)]
        has_project_title = _work_group_has_project_title(group)
        if not group or not has_project_title:
            continue
        title = _title_for_work_candidate(work_item, group)
        if (not title or _is_role_only_title(title)) and has_project_title:
            title = str(work_item.get("company_name", "")).strip() or _summarize_title(group[0].text)
        if not title:
            title = str(work_item.get("job_title_raw", "") or work_item.get("company_name", "")).strip() or _summarize_title(group[0].text)
        results.append(
            _candidate_payload(
                index=len(results) + 1,
                group=group,
                section_name="work",
                concepts=concepts,
                domains=domains,
                candidate_type="work_embedded_project_title" if has_project_title else "work_scope_group",
                title=title,
                organization_raw=str(work_item.get("company_name", "")).strip() or _extract_organization_hint(group[0].text),
                confidence=0.78 if has_project_title else 0.7,
                parent_work_experience_ref=str(work_item.get("work_ref", "") or "").strip(),
            )
        )
        used_block_ids.update(block.block_id for block in group)
    project_blocks = [block for block in blocks if section_lookup.get(block.block_id, "") == "project" and block.block_id not in used_block_ids]
    results.extend(
        _build_project_section_candidates(
            project_blocks=project_blocks,
            start_index=len(results) + 1,
            concepts=concepts,
            domains=domains,
            cleanup_config=dict(chunking_config.project_cleanup or {}),
        )
    )
    if results:
        return _dedupe_project_candidates(results)[:12]
    groups: List[List[DocumentBlock]] = []
    current: List[DocumentBlock] = []
    current_section = ""
    for block in blocks:
        section_name = section_lookup.get(block.block_id, "") or "unknown"
        text = block.text.strip()
        if not text:
            continue
        seed = _is_chunk_seed(
            text=text,
            section_name=section_name,
            keep_keywords=chunking_config.keep_keywords,
            concepts=concepts,
            domains=domains,
        )
        if current and (section_name != current_section or seed):
            groups.append(current)
            current = []
        if seed or current:
            current.append(block)
            current_section = section_name
    if current:
        groups.append(current)
    results: List[Dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        section_name = section_lookup.get(group[0].block_id, "") or "unknown"
        if len(group) == 1 and _is_role_only_title(group[0].text):
            continue
        candidate = _candidate_payload(
            index=index,
            group=group,
            section_name=section_name,
            concepts=concepts,
            domains=domains,
            candidate_type="standalone_project_title" if section_name == "project" else "work_scope_group",
            title=_summarize_title(group[0].text.strip()),
            organization_raw=_extract_organization_hint(group[0].text.strip()),
            confidence=0.72 if section_name == "project" else 0.68,
        )
        if section_name in {"project", "work"}:
            results.append(candidate)
    return _dedupe_project_candidates(results)[:16]


def _build_project_section_candidates(
    *,
    project_blocks: List[DocumentBlock],
    start_index: int,
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
    cleanup_config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    groups: List[List[DocumentBlock]] = []
    current: List[DocumentBlock] = []
    for block in project_blocks:
        text = _normalize_content_text(block.text)
        if _is_section_heading(text):
            if current:
                groups.append(current)
                current = []
            continue
        if _is_project_page_header_noise(text):
            continue
        if _is_project_section_tail_boundary(text, cleanup_config):
            if current:
                groups.append(current)
                current = []
            continue
        if _looks_like_structural_project_title(text):
            if current:
                groups.append(current)
            current = [block]
            continue
        if not current and _looks_like_project_content(text):
            current = [block]
            continue
        if current:
            current.append(block)
    if current:
        groups.append(current)
    results: List[Dict[str, Any]] = []
    for offset, group in enumerate(groups):
        title = _project_title_from_group(group)
        if not title or _is_section_heading(title):
            continue
        results.append(
            _candidate_payload(
                index=start_index + offset,
                group=group,
                section_name="project",
                concepts=concepts,
                domains=domains,
                candidate_type="standalone_project_title",
                title=title,
                organization_raw=_project_organization_from_group(group),
                confidence=0.82,
            )
        )
    return results


def _project_organization_from_group(group: List[DocumentBlock]) -> str:
    if len(group) <= 1:
        return ""
    candidate = _clean_project_title_candidate(group[1].text)
    if not candidate or candidate.startswith(("-", "•", "*", "", "")):
        return ""
    if _starts_with_project_action(candidate) or _looks_like_project_content(candidate):
        return ""
    return _extract_organization_hint(candidate)


def _project_section_blocks_from_actions(block_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "sequence_no": item.get("sequence_no", 0),
            "block_id": item.get("block_id", ""),
            "text": str(item.get("text", "") or ""),
            "page_no": item.get("page_no", 0),
            "section": item.get("section", ""),
            "block_action": item.get("block_action", ""),
        }
        for item in block_actions
        if item.get("section") == "project" and item.get("block_action") != "hard_drop"
    ]


def _project_repair_blocks_from_actions(block_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    project_blocks = _project_section_blocks_from_actions(block_actions)
    if project_blocks:
        return project_blocks
    work_blocks = [
        {
            "sequence_no": item.get("sequence_no", 0),
            "block_id": item.get("block_id", ""),
            "text": str(item.get("text", "") or ""),
            "page_no": item.get("page_no", 0),
            "section": item.get("section", ""),
            "block_action": item.get("block_action", ""),
        }
        for item in block_actions
        if item.get("section") == "work" and item.get("block_action") != "hard_drop"
    ]
    while work_blocks and _is_date_only_repair_noise(str(work_blocks[-1].get("text", "") or "")):
        work_blocks.pop()
    return work_blocks if _work_blocks_look_like_project_spans(work_blocks) else []


def _is_date_only_repair_noise(text: str) -> bool:
    cleaned = _normalize_content_text(text)
    if not cleaned or len(cleaned) > 60:
        return False
    cleaned = re.sub(r"\bM\s+ay\b", "May", cleaned, flags=re.IGNORECASE)
    without_dates = DATE_RANGE_RE.sub("", cleaned)
    without_dates = re.sub(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\b", "", without_dates, flags=re.IGNORECASE)
    without_dates = re.sub(r"\b(?:19|20)\d{2}\b", "", without_dates)
    without_dates = re.sub(r"[\s./\\–—~至到年月-]+", "", without_dates)
    return not without_dates


def _work_blocks_look_like_project_spans(blocks: List[Dict[str, Any]]) -> bool:
    heading_count = 0
    bullet_count = 0
    for block in blocks:
        text = str(block.get("text", "") or "").strip()
        if _looks_like_work_project_heading(text):
            heading_count += 1
        elif _starts_with_project_action(text) or text.startswith("-"):
            bullet_count += 1
    return heading_count >= 2 and bullet_count >= heading_count


def _looks_like_work_project_heading(text: str) -> bool:
    cleaned = _clean_heading_text(text)
    if not cleaned or _is_section_heading(cleaned) or DATE_RANGE_RE.search(cleaned):
        return False
    lowered = cleaned.lower()
    if len(cleaned) > 120:
        return False
    return any(
        token in lowered
        for token in (
            "intern",
            "developer",
            "engineer",
            "machine learning",
            "recommendation",
            "rest api",
            "system",
            "trader",
            "backtesting",
        )
    )


def _assess_project_boundary_quality(
    *,
    project_section_blocks: List[Dict[str, Any]],
    project_candidate_groups: List[Dict[str, Any]],
) -> Dict[str, Any]:
    candidate_evidence_sets = [
        set(str(block_id) for block_id in list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []))
        for item in project_candidate_groups
    ]
    reasons: List[str] = []
    missing_headings: List[str] = []
    fragmented_titles: List[str] = []
    subsection_titles: List[str] = []

    for index, block in enumerate(project_section_blocks):
        text = str(block.get("text", "") or "")
        block_id = str(block.get("block_id", "") or "")
        if not _looks_like_structural_project_title(text):
            continue
        if block_id and not any(block_id in evidence for evidence in candidate_evidence_sets):
            missing_headings.append(_clean_heading_text(text)[:80])
        span = _project_span_from_title(project_section_blocks, index)
        numbered_ids = [
            str(item.get("block_id", "") or "")
            for item in span
            if _is_numbered_project_detail(str(item.get("text", "") or ""))
        ]
        if len(numbered_ids) >= 2 and not any(set(numbered_ids).issubset(evidence) for evidence in candidate_evidence_sets):
            fragmented_titles.append(_clean_heading_text(text)[:80])
        has_subsection = any(_is_project_subsection_heading(str(item.get("text", "") or "")) for item in span[1:])
        span_ids = {
            str(item.get("block_id", "") or "")
            for item in span
            if str(item.get("block_id", "") or "") and not _is_project_page_header_noise(str(item.get("text", "") or ""))
        }
        if has_subsection and len(span_ids) >= 3 and not any(span_ids.issubset(evidence) for evidence in candidate_evidence_sets):
            subsection_titles.append(_clean_heading_text(text)[:80])

    single_line_candidates = [
        item
        for item in project_candidate_groups
        if len(list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or [])) <= 1
    ]
    if missing_headings:
        reasons.append("missing_heading_candidate")
    if fragmented_titles:
        reasons.append("numbered_list_fragmented")
    if subsection_titles:
        reasons.append("subsection_split")
    if len(project_candidate_groups) >= 8 and len(single_line_candidates) >= max(4, len(project_candidate_groups) // 2):
        reasons.append("too_many_single_line_candidates")
    status = "repair_required" if reasons else "good"
    return {
        "status": status,
        "reasons": reasons,
        "missing_heading_titles": missing_headings[:6],
        "fragmented_titles": fragmented_titles[:6],
        "subsection_titles": subsection_titles[:6],
        "project_section_block_count": len(project_section_blocks),
        "candidate_count": len(project_candidate_groups),
        "single_line_candidate_count": len(single_line_candidates),
    }


def _project_span_from_title(project_section_blocks: List[Dict[str, Any]], start_index: int) -> List[Dict[str, Any]]:
    span: List[Dict[str, Any]] = []
    for index in range(start_index, len(project_section_blocks)):
        text = str(project_section_blocks[index].get("text", "") or "")
        if index > start_index and _looks_like_structural_project_title(text):
            break
        if index > start_index and _is_section_heading(_normalize_content_text(text)):
            break
        span.append(project_section_blocks[index])
    return span


def _looks_like_structural_project_title(text: str) -> bool:
    raw = str(text or "").strip()
    cleaned = _clean_heading_text(raw)
    title_candidate = _clean_project_title_candidate(raw)
    marker_cleaned = re.sub(r"^[#\s•*\-]+", "", title_candidate).strip()
    if not title_candidate or _is_section_heading(title_candidate) or _is_project_subsection_heading(cleaned):
        return False
    if DATE_RANGE_RE.fullmatch(title_candidate) or MONTH_DATE_RANGE_RE.fullmatch(title_candidate):
        return False
    if len(title_candidate) > 90:
        return False
    if re.match(r"^\d+[.、]\s*", title_candidate) and _is_numbered_project_detail(title_candidate):
        return False
    if raw.startswith("#"):
        if len(marker_cleaned) <= 4 and not _looks_like_project_title(marker_cleaned):
            return False
        return True
    has_bullet_marker = raw.startswith(("•", "-", "*", ""))
    has_numbered_marker = re.match(r"^\d+[.、]\s*(?:[•]\s*)?\S+", title_candidate)
    if (has_bullet_marker or has_numbered_marker) and _starts_with_project_action(marker_cleaned):
        return False
    if (has_bullet_marker or has_numbered_marker) and not _looks_like_project_title(marker_cleaned):
        return False
    if _looks_like_project_title(marker_cleaned or title_candidate):
        return True
    return False


def _starts_with_project_action(text: str) -> bool:
    cleaned = _clean_heading_text(text).strip()
    matched = re.match(r"^\d+[.、]\s*(?:[•]\s*)?(.+)", cleaned)
    if matched:
        cleaned = matched.group(1).strip()
    action_prefixes = (
        "实现", "开发", "负责", "参与", "完成", "搭建", "构建", "优化", "设计", "引入",
        "支持", "保证", "提升", "解决", "分析", "整理", "输出", "使用", "通过", "基于",
        "采用", "利用", "创建", "employed", "created", "developed", "used", "built",
    )
    return cleaned.lower().startswith(action_prefixes)


def _is_project_subsection_heading(text: str) -> bool:
    normalized = re.sub(r"[\s:：#•\-*]+", "", _normalize_heading(text))
    return normalized in {
        "项目简介",
        "项目介绍",
        "项目描述",
        "项目背景",
        "工作简介",
        "工作业绩",
        "负责内容",
        "工作内容",
        "职责描述",
        "技术栈",
        "技术方案",
        "收获总结",
        "项目成果",
        "成果总结",
        "主要职责",
    }


def _is_project_section_tail_boundary(text: str, cleanup_config: Dict[str, Any]) -> bool:
    raw = str(text or "").strip()
    cleaned = _clean_heading_text(raw)
    if not cleaned:
        return False
    if PHONE_RE.search(cleaned) or EMAIL_RE.search(cleaned):
        return True
    tail_tokens = _string_list_from_config(cleanup_config.get("tail_boundary_tokens"))
    if any(token in cleaned for token in tail_tokens):
        return True
    if raw.startswith("#") and _looks_like_name(cleaned):
        return True
    return False


def _is_project_page_header_noise(text: str) -> bool:
    raw = str(text or "").strip()
    cleaned = _clean_heading_text(raw)
    if not cleaned:
        return False
    if PHONE_RE.search(cleaned) or EMAIL_RE.search(cleaned):
        return True
    return raw.startswith("#") and _looks_like_name(cleaned)


def _is_numbered_project_detail(text: str) -> bool:
    cleaned = _clean_heading_text(text)
    matched = re.match(r"^\d+[.、]\s*(.+)", cleaned)
    if not matched:
        return False
    body = matched.group(1).strip()
    action_prefixes = (
        "实现", "开发", "负责", "参与", "完成", "搭建", "构建", "优化", "设计", "引入",
        "支持", "保证", "提升", "解决", "分析", "整理", "输出", "使用", "通过", "基于",
    )
    return body.startswith(action_prefixes) or len(body) > 36


def _candidate_payload(
    *,
    index: int,
    group: List[DocumentBlock],
    section_name: str,
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
    candidate_type: str,
    title: str,
    organization_raw: str,
    confidence: float,
    parent_work_experience_ref: str = "",
) -> Dict[str, Any]:
    text = "\n".join(block.text.strip() for block in group if block.text.strip())
    chunk_concepts, chunk_domains = _extract_concept_and_domain_tags(group, concepts, domains)
    skill_tags = _extract_skill_tags(group, concepts).get("normalized", [])
    return {
        "chunk_id": f"chunk_{index}",
        "chunk_title": _summarize_title(title),
        "chunk_text": text,
        "source_section": section_name,
        "candidate_type": candidate_type,
        "date_range_raw": _extract_date_range_raw(text),
        "organization_raw": organization_raw,
        "concept_tags": chunk_concepts,
        "domain_tags": chunk_domains,
        "skill_tags": skill_tags,
        "confidence": confidence,
        "evidence": build_evidence(group),
        "source": "rule",
        "parent_work_experience_ref": parent_work_experience_ref,
    }


def _title_for_work_candidate(work_item: Dict[str, Any], group: List[DocumentBlock]) -> str:
    for block in group:
        if _is_bullet_or_detail_project_title_noise(block.text):
            continue
        text = _clean_heading_text(block.text)
        if _looks_like_project_title(text):
            return text
    company = str(work_item.get("company_name", "")).strip()
    summary = str(work_item.get("summary_raw", "")).strip()
    if company and "支付" in summary:
        return f"{company} 支付系统相关工作块"
    if company:
        return f"{company} 工作项目候选组"
    return _summarize_title(group[0].text)


def _work_group_has_project_title(group: List[DocumentBlock]) -> bool:
    return any(
        not _is_bullet_or_detail_project_title_noise(block.text)
        and _looks_like_project_title(_clean_heading_text(block.text))
        for block in group
    )


def _work_item_has_project_scope(work_item: Dict[str, Any], group: List[DocumentBlock]) -> bool:
    evidence_ids = list(dict(work_item.get("evidence", {}) or {}).get("block_ids", []) or [])
    if len(evidence_ids) < 3:
        return False
    text = " ".join(
        [
            str(work_item.get("job_title_raw", "") or ""),
            str(work_item.get("summary_raw", "") or ""),
            " ".join(block.text for block in group),
        ]
    ).lower()
    scope_tokens = (
        "system", "platform", "api", "service", "algorithm", "model", "machine learning",
        "recommendation", "backtesting", "insurance", "trader", "project", "系统", "平台",
        "模型", "算法", "推荐", "搜索", "项目",
    )
    action_tokens = (
        "developed", "created", "implemented", "architected", "designed", "employed",
        "开发", "实现", "设计", "构建", "优化",
    )
    return any(token in text for token in scope_tokens) and any(token in text for token in action_tokens)


def _looks_like_project_title(text: str) -> bool:
    if _is_bullet_or_detail_project_title_noise(text):
        return False
    cleaned = _clean_project_title_candidate(text)
    if not cleaned or _is_section_heading(cleaned) or _is_role_only_title(cleaned):
        return False
    if cleaned.startswith(("-", "•", "*")):
        return False
    if len(cleaned) > 80:
        return False
    project_tokens = (
        "项目", "系统", "平台", "引擎", "解析", "推荐", "搜索", "交易", "风控", "中台",
        "模型", "算法", "检索", "识别", "搜推", "首页", "redis", "golang", "go语言", "机器学习",
        "chatbot", "agent", "orchestration", "inference", "benchmarking",
    )
    lowered = cleaned.lower()
    return any(token in cleaned or token in lowered for token in project_tokens)


def _is_bullet_or_detail_project_title_noise(text: str) -> bool:
    normalized = _normalize_content_text(text).strip()
    if not normalized:
        return False
    if normalized.startswith(("-", "•", "*", "", "")):
        return True
    action_prefixes = (
        "负责", "参与", "推动", "设计", "开发", "实现", "构建", "搭建", "优化", "使用", "支持",
        "developed", "implemented", "designed", "built", "optimized",
    )
    lowered = normalized.lower()
    if any(lowered.startswith(prefix.lower()) for prefix in action_prefixes):
        return True
    return len(normalized) > 80 and _looks_like_work_detail_line(normalized)


def _clean_project_title_candidate(text: str) -> str:
    cleaned = _clean_heading_text(text)
    cleaned = MONTH_DATE_RANGE_RE.sub("", DATE_RANGE_RE.sub("", cleaned))
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" -|•")


def _looks_like_project_content(text: str) -> bool:
    cleaned = _clean_heading_text(text)
    if not cleaned or _is_non_project_noise(cleaned):
        return False
    project_tokens = ("项目", "课题", "研究", "实验", "系统", "平台")
    action_tokens = ("参与", "负责", "开发", "构建", "优化", "分析", "研究", "寻找")
    return any(token in cleaned for token in project_tokens) and any(token in cleaned for token in action_tokens)


def _project_title_from_group(group: List[DocumentBlock]) -> str:
    text = _clean_project_title_candidate(group[0].text if group else "")
    if not text:
        return ""
    matched = re.search(r"((?:大学生创新)?项目[^,，。；;]{2,40})", text)
    if matched:
        return matched.group(1).strip()
    matched = re.search(r"((?:科研|研究|实验)[^,，。；;]{2,40})", text)
    if matched:
        return matched.group(1).strip()
    return text if _looks_like_project_title(text) else _summarize_title(text)


def _is_non_project_noise(text: str) -> bool:
    cleaned = _clean_heading_text(text)
    if not cleaned:
        return True
    if cleaned == "考研" or cleaned.startswith("考研 "):
        return True
    noise_tokens = ("熟练使用", "可以熟练", "兴趣爱好", "获奖证书", "主修课程", "联系电话", "邮箱")
    return any(token in cleaned for token in noise_tokens)


def _is_role_only_title(text: str) -> bool:
    cleaned = _clean_heading_text(text)
    if not cleaned:
        return False
    if any(token in cleaned for token in ("项目", "系统", "平台", "引擎", "解析", "推荐", "搜索", "交易")):
        return False
    role_tokens = ("工程师", "开发", "Developer", "Engineer", "后端", "前端", "全栈", "算法")
    return any(token in cleaned for token in role_tokens)


def _is_section_heading(text: str) -> bool:
    normalized = _normalize_heading(text)
    return normalized in {
        "项目经历", "项目经验", "项目背景", "科研经历", "科研项目", "研究经历", "研究项目",
        "个人项目", "个人项目经历",
        "project", "projects", "personalproject", "personalprojects",
        "workexperience", "workhistory", "experience", "工作经历", "工作经验",
        "education", "教育背景", "个人技能", "专业技能", "技能", "skills",
        "兴趣爱好", "获奖证书", "自我评价", "summary", "profile", "作品集", "图文作品集",
    }


def _dedupe_project_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in candidates:
        key = _candidate_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _candidate_dedupe_key(item: Dict[str, Any]) -> Tuple[str, str, str, str]:
    evidence_ids = tuple(sorted(str(value) for value in list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or [])))
    return (
        _normalize_match_key(str(item.get("chunk_title", "") or "")),
        _normalize_match_key(str(item.get("organization_raw", "") or "")),
        _normalize_match_key(str(item.get("date_range_raw", "") or "")),
        "|".join(evidence_ids),
    )


def _collect_concept_hits(text: str, concepts: Dict[str, Dict[str, Any]]) -> List[str]:
    hits: List[str] = []
    lower = text.lower()
    for concept_name, entry in concepts.items():
        aliases = [concept_name, *(entry.get("aliases", []) or [])]
        if any(alias.lower() in lower for alias in aliases):
            hits.append(concept_name)
    return hits[:12]


def _collect_domain_hits(text: str, domains: Dict[str, DomainConfig]) -> List[str]:
    hits: List[str] = []
    lower = text.lower()
    for domain in domains.values():
        aliases = [domain.domain_name, *domain.aliases, *domain.search_hints]
        if any(alias.lower() in lower for alias in aliases):
            hits.append(domain.domain_name)
    return hits[:8]


def _extract_dates(text: str) -> Tuple[str, str]:
    normalized = _normalize_month_spacing(_normalize_content_text(text))
    present_match = MONTH_TO_PRESENT_RE.search(normalized)
    if present_match:
        return f"{present_match.group('start_year')}-{_month_number(present_match.group('start_month'))}", present_match.group("end")
    month_match = MONTH_DATE_RANGE_RE.search(normalized)
    if month_match:
        start_year = month_match.group("start_year") or month_match.group("end_year")
        end_year = month_match.group("end_year")
        return (
            f"{start_year}-{_month_number(month_match.group('start_month'))}",
            f"{end_year}-{_month_number(month_match.group('end_month'))}",
        )
    match = DATE_RANGE_RE.search(normalized)
    if not match:
        return "", ""
    return match.group("start"), match.group("end")


def _extract_date_range_raw(text: str) -> str:
    normalized = _normalize_month_spacing(_normalize_content_text(text))
    match = MONTH_TO_PRESENT_RE.search(normalized) or MONTH_DATE_RANGE_RE.search(normalized) or DATE_RANGE_RE.search(normalized)
    return match.group(0) if match else ""


def _strip_date_ranges(text: str) -> str:
    normalized = _normalize_month_spacing(_normalize_content_text(text))
    return DATE_RANGE_RE.sub("", MONTH_DATE_RANGE_RE.sub("", MONTH_TO_PRESENT_RE.sub("", normalized)))


def _normalize_month_spacing(text: str) -> str:
    return re.sub(r"\bM\s+ay\b", "May", text, flags=re.IGNORECASE)


def _month_number(month: str) -> str:
    return MONTH_NAME_TO_NUMBER.get(month[:4].lower().rstrip("."), MONTH_NAME_TO_NUMBER.get(month[:3].lower().rstrip("."), "01"))


def _extract_organization_hint(text: str) -> str:
    left = DATE_RANGE_RE.sub("", _normalize_content_text(text)).strip()
    parts = re.split(r"\s{2,}|\s+\|\s+|\s+-\s+", left)
    return parts[0].strip() if parts else left[:48]


def _guess_title_from_text(text: str, company: str) -> str:
    guess = text.replace(company, "", 1).strip(" -|：:")
    return guess or text


def _looks_like_name(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 12:
        return False
    if any(
        token in stripped
        for token in (
            "电话",
            "邮箱",
            "简历",
            "求职",
            "工程师",
            "开发",
            "大学",
            "教育",
            "工作",
            "经历",
            "项目",
            "技能",
            "兴趣",
            "爱好",
            "获奖",
            "证书",
            "自我",
            "作品",
            "背景",
            "Huawei",
            "Software",
            "University",
            "College",
        )
    ):
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,20}|[\u4e00-\u9fff]{2,4}", stripped))


def _has_contact_or_intent_nearby(blocks: List[DocumentBlock], index: int) -> bool:
    start = max(0, index - 3)
    end = min(len(blocks), index + 6)
    window = "\n".join(_normalize_content_text(block.text) for block in blocks[start:end])
    return bool(PHONE_RE.search(window) or EMAIL_RE.search(window) or any(token in window for token in ("求职意向", "目标职位", "手机", "邮箱", "微信")))


def _normalize_heading(text: str) -> str:
    lowered = unicodedata.normalize("NFKC", text or "").strip().lower()
    lowered = lowered.lstrip("#").strip()
    lowered = re.sub(r"[\s:：|·•·\-_/]+", "", lowered)
    return lowered


def _is_decorative_block(text: str) -> bool:
    if not text:
        return True
    if len(text) <= 2 and all(not ch.isalnum() for ch in text):
        return True
    if re.fullmatch(r"[-_=*|•·\s]{3,}", text):
        return True
    return False


def _looks_like_experience_line(text: str) -> bool:
    normalized = _normalize_content_text(text)
    return bool(DATE_RANGE_RE.search(normalized)) or any(token in normalized for token in ("负责", "开发", "项目", "系统", "平台", "实习", "工程师"))


def _summarize_title(text: str) -> str:
    cleaned = MONTH_DATE_RANGE_RE.sub("", DATE_RANGE_RE.sub("", text)).strip(" -|：:")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned[:60]


def _is_chunk_seed(
    *,
    text: str,
    section_name: str,
    keep_keywords: List[str],
    concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
) -> bool:
    lower = _normalize_content_text(text).lower()
    if section_name in {"work", "project"} and (_looks_like_experience_line(text) or len(text) >= 16):
        return True
    if any(keyword.lower() in lower for keyword in keep_keywords):
        return True
    if _collect_concept_hits(text, concepts) or _collect_domain_hits(text, domains):
        return True
    return False


def _dedupe_scored_values(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for item in items:
        value = str(item.get("value", "")).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(item)
    return deduped


def _normalize_content_text(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).replace("\x00", "").strip()
