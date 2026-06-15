from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterable

from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.rules.taxonomy import match_taxonomy, normalize_taxonomy_key, taxonomy_entries
from resume_query_ai_qa.core.schemas import NormalizedCondition, QueryCondition


def extract_conditions(question: str) -> list[QueryCondition]:
    """提取条件集合并返回。"""
    text = str(question or "").strip()
    output: list[QueryCondition] = []
    major_values: list[str] = []
    extraction = dict(_condition_rules().get("extraction", {}) or {})
    major_pattern = str(extraction.get("major_pattern", "") or "")
    for matched in re.finditer(major_pattern, text, re.IGNORECASE) if major_pattern else []:
        value = _clean_major_value(matched.group(1))
        if value:
            major_values.append(value)
            output.append(QueryCondition(type="major", raw_value=value, evidence=matched.group(0), reason="matched education major"))
    for entry in _taxonomy_entries():
        for alias in entry.aliases:
            if _contains(text, alias):
                if _is_taxonomy_alias_excluded(text, alias):
                    continue
                if entry.type == "domain" and any(_major_overlaps_alias(major, alias) for major in major_values):
                    continue
                output.append(
                    QueryCondition(
                        type=entry.type,
                        raw_value=alias,
                        evidence=alias,
                        reason=f"matched {entry.type} alias",
                    )
                )
                break
    for scope in list(extraction.get("scopes", []) or []):
        pattern = str(dict(scope or {}).get("pattern", "") or "")
        value = str(dict(scope or {}).get("value", "") or "")
        if not pattern or not value:
            continue
        matched = re.search(pattern, text, re.IGNORECASE)
        if matched:
            output.append(QueryCondition(type="scope", raw_value=value, evidence=matched.group(1), reason="matched scope"))
    return _dedupe_conditions(output)


def normalize_conditions(conditions: Iterable[QueryCondition]) -> list[NormalizedCondition]:
    """标准化条件集合并返回。"""
    normalized: list[NormalizedCondition] = []
    for condition in conditions:
        raw_value = str(condition.raw_value or condition.evidence or "").strip()
        if not raw_value:
            continue
        if condition.type == "candidate_name":
            normalized.append(
                NormalizedCondition(
                    type="candidate_name",
                    raw_value=raw_value,
                    normalized_value=raw_value,
                    evidence=condition.evidence or raw_value,
                    matched_by="candidate_mention_raw",
                    confidence=0.8,
                    retrieval_terms=[raw_value],
                )
            )
            continue
        matches = _match_condition(raw_value, condition.type)
        if matches:
            for match in matches:
                normalized.append(
                    NormalizedCondition(
                        type=match["type"],
                        raw_value=raw_value,
                        normalized_value=match["value"],
                        evidence=condition.evidence or raw_value,
                        matched_by=match["matched_by"],
                        confidence=match["confidence"],
                        retrieval_terms=_dedupe_terms([raw_value, *match["retrieval_terms"]]),
                    )
                )
            continue
        normalized.append(
            NormalizedCondition(
                type=condition.type or "keyword",
                raw_value=raw_value,
                normalized_value=raw_value,
                evidence=condition.evidence or raw_value,
                matched_by="unmatched_raw",
                confidence=0.5,
                retrieval_terms=[raw_value],
            )
        )
    return _dedupe_normalized(normalized)


def normalize_domain(value: str | None) -> str | None:
    """标准化领域并返回。"""
    if not value:
        return value
    matches = _match_condition(str(value), "domain")
    for match in matches:
        if match["type"] == "domain":
            return str(match["value"])
    return value


def cleaned_retrieval_query(conditions: Iterable[NormalizedCondition], fallback: str = "") -> str:
    """获取清理后检索查询并返回。"""
    terms: list[str] = []
    types = dict(_condition_rules().get("condition_types", {}) or {})
    for condition in conditions:
        if not bool(dict(types.get(condition.type, {}) or {}).get("retrievable", False)):
            continue
        terms.extend(condition.retrieval_terms or [])
    if not terms and fallback:
        terms = [fallback]
    return " ".join(_dedupe_terms(terms)).strip()


def filter_arguments_from_conditions(
    conditions: Iterable[NormalizedCondition],
    question: str = "",
    *,
    include_preference_domains: bool = False,
    include_preference_targets: bool = False,
) -> dict[str, Any]:
    """从条件集合提取筛选参数集合并返回。"""
    args: dict[str, Any] = {}
    domains: list[str] = []
    skills: list[str] = []
    concepts: list[str] = []
    keywords: list[str] = []
    education_keywords: list[str] = []
    for condition in conditions:
        value = str(condition.normalized_value or "").strip()
        if not value:
            continue
        if condition.matched_by.startswith("preference_target:"):
            if include_preference_targets:
                if condition.type == "domain":
                    domains.append(value)
                elif condition.type == "skill":
                    skills.append(value)
                elif condition.type == "concept":
                    concepts.append(value)
                elif condition.type == "job_intent":
                    keywords.extend(condition.retrieval_terms or [value])
                elif condition.type in {"keyword", "experience"}:
                    keywords.append(value)
            elif include_preference_domains and condition.type == "domain":
                domains.append(value)
            continue
        if condition.type == "domain":
            domains.append(value)
        elif condition.type == "major":
            education_keywords.extend(condition.retrieval_terms or [value])
        elif condition.type == "skill":
            skills.append(value)
        elif condition.type == "concept":
            concepts.append(value)
        elif condition.type in {"keyword", "experience"}:
            keywords.append(value)
    if domains:
        domain_key = "domains_all" if _requires_all_domains(question) else "domains_any"
        args[domain_key] = _dedupe_terms(domains)
    if skills:
        args["skills_all"] = _dedupe_terms(skills)
    if concepts:
        args["concepts_all"] = _dedupe_terms(concepts)
    if keywords:
        args["keywords"] = _dedupe_terms(keywords)
    if education_keywords:
        args["education_keywords"] = _dedupe_terms(education_keywords)
    return args


def mark_preference_targets(conditions: list[NormalizedCondition], question: str) -> list[NormalizedCondition]:
    """获取markpreferencetargets并返回。"""
    text = str(question or "")
    policy = dict(_condition_rules().get("preference_target", {}) or {})
    patterns = [str(item) for item in list(policy.get("patterns", []) or []) if str(item).strip()]
    legacy_pattern = str(policy.get("pattern", "") or "")
    if legacy_pattern:
        patterns.append(legacy_pattern)
    matched = _first_pattern_match(patterns, text)
    if not matched:
        return conditions
    filter_text = text[: matched.start()]
    target_text = matched.group(1)
    output: list[NormalizedCondition] = []
    for condition in conditions:
        raw = str(condition.raw_value or condition.evidence or "").strip()
        eligible_types = {str(item) for item in list(policy.get("eligible_types", []) or [])}
        if condition.type in eligible_types and raw and _contains(target_text, raw) and not _contains(filter_text, raw):
            output.append(condition.model_copy(update={"matched_by": f"preference_target:{condition.matched_by}"}))
        else:
            output.append(condition)
    return output


def _first_pattern_match(patterns: Iterable[str], text: str) -> re.Match[str] | None:
    """返回第一条能提取偏好目标的规则匹配。"""
    for pattern in patterns:
        matched = re.search(pattern, text, re.IGNORECASE)
        if matched and matched.lastindex and str(matched.group(1) or "").strip():
            return matched
    return None


def _requires_all_domains(question: str) -> bool:
    """获取requires全部domains并返回。"""
    text = str(question or "")
    policy = dict(_condition_rules().get("domain_filter", {}) or {})
    return any(str(token) in text for token in list(policy.get("intersection_terms", []) or []))


def _is_taxonomy_alias_excluded(text: str, alias: str) -> bool:
    """判断分类别名在当前上下文中是否只是动作词。"""
    alias_key = _normalize_key(alias)
    if not alias_key:
        return False
    text_key = _normalize_key(text)
    for item in list(_condition_rules().get("taxonomy_alias_exclusions", []) or []):
        rule = dict(item or {})
        if _normalize_key(str(rule.get("alias", "") or "")) != alias_key:
            continue
        for pattern in list(rule.get("when_matching", []) or []):
            if re.search(str(pattern), text, re.IGNORECASE):
                return True
        for suffix in list(rule.get("when_followed_by", []) or []):
            if _normalize_key(f"{alias}{suffix}") in text_key:
                return True
    return False


def _match_condition(raw_value: str, preferred_type: str = "") -> list[dict[str, Any]]:
    """匹配结果条件并返回匹配结果。"""
    return match_taxonomy(raw_value, _preferred_entry_types(preferred_type))


def _preferred_entry_types(condition_type: str) -> set[str]:
    """获取preferred条目类型集合并返回。"""
    key = _normalize_key(condition_type)
    aliases = dict(_condition_rules().get("preferred_type_aliases", {}) or {})
    if any(_normalize_key(item) in key for item in list(aliases.get("domain", []) or [])):
        return {"domain"}
    if any(_normalize_key(item) in key for item in list(aliases.get("major", []) or [])):
        return {"major"}
    if any(_normalize_key(item) in key for item in list(aliases.get("skill_concept", []) or [])):
        return {"skill", "concept", "domain"}
    if any(_normalize_key(item) in key for item in list(aliases.get("scope", []) or [])):
        return {"scope"}
    return set()


@lru_cache(maxsize=1)
def _taxonomy_entries():
    """获取分类体系条目集合并返回。"""
    return taxonomy_entries()


@lru_cache(maxsize=1)
def _condition_rules() -> dict[str, Any]:
    """获取条件规则集合并返回。"""
    return dict(load_config().condition_rules or {})


def _contains(text: str, alias: str) -> bool:
    """判断结果是否成立并返回布尔值。"""
    return _normalize_key(alias) in _normalize_key(text)


def _normalize_key(value: str) -> str:
    """标准化键并返回。"""
    return normalize_taxonomy_key(value)


def _clean_major_value(value: str) -> str:
    """清理major值并返回。"""
    text = str(value or "").strip(" ，,。；;:：?？")
    cleaning = dict(_condition_rules().get("cleaning", {}) or {})
    for prefix in list(cleaning.get("major_prefixes", []) or []):
        if text.startswith(prefix):
            text = text[len(prefix):].strip(" ，,。；;:：?？")
    return text.strip("的 人 候选人")


def _major_overlaps_alias(major: str, alias: str) -> bool:
    """获取majoroverlaps别名并返回。"""
    major_key = _normalize_key(major)
    alias_key = _normalize_key(alias)
    return bool(major_key and alias_key and (major_key in alias_key or alias_key in major_key))


def _dedupe_conditions(values: list[QueryCondition]) -> list[QueryCondition]:
    """去重条件集合并返回。"""
    output: list[QueryCondition] = []
    seen: set[str] = set()
    for value in sorted(values, key=lambda item: len(item.raw_value or item.evidence), reverse=True):
        raw_key = _normalize_key(value.raw_value or value.evidence)
        key = f"{value.type}:{raw_key}"
        if not raw_key or key in seen:
            continue
        if any(old.startswith(f"{value.type}:") and raw_key in old.split(":", 1)[1] for old in seen):
            continue
        seen.add(key)
        output.append(value)
    return sorted(output, key=lambda item: values.index(item) if item in values else 0)


def _dedupe_terms(values: Iterable[str]) -> list[str]:
    """去重词项集合并返回。"""
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        key = _normalize_key(item)
        if not item or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _dedupe_matches(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按条件匹配键去重并返回匹配结果。"""
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (str(value.get("type", "")), str(value.get("value", "")))
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _dedupe_normalized(values: list[NormalizedCondition]) -> list[NormalizedCondition]:
    """去重标准化并返回。"""
    output: list[NormalizedCondition] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (value.type, _normalize_key(value.raw_value), _normalize_key(value.normalized_value))
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output
