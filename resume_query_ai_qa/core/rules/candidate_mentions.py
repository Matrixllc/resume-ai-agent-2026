"""Shared candidate mention extraction for router and resolver."""

from __future__ import annotations

import re

from resume_query_ai_qa.core.rules.taxonomy import aliases_for_types, regex_terms_for_types


_MENTION_PATTERN_TEMPLATES = [
    r"(?:这里面(?:的)?|其中(?:的)?|这些人里(?:的)?)\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,12}?)(?:项目经验|项目经历|项目|个人信息|信息|资料|经历|背景|工作|有没有|是否有|有无|适不适合|是否适合|适合)",
    r"(?:分析|判断|评估)\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,12}?)(?:适不适合|是否适合|适合|能不能做|能否胜任|可不可以做)",
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,12}?)(?:适不适合|是否适合|适合|能不能做|能否胜任|可不可以做)",
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,12}?)(?:项目经验|项目经历)(?:是什么|有哪些|有什么)",
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{0,30}?)的(?:项目|个人信息|信息|资料|经历|背景|工作|profile|experience)",
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,30}?)(?:有没有|是否有|有无|有)(?:__TAXONOMY_TERMS__)?(?:项目|经历|经验|背景|工作|project|experience)",
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,30}?)(?:有哪些|有什么)(?:__TAXONOMY_TERMS__)?(?:项目|经历|经验|背景|工作|project|experience)",
    r"(?:介绍一下|介绍|查看|看下|看一下|显示|展示|tell me about)\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,30})",
    r"(?:对|针对|围绕)\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ._-]{1,30}?)(?:的)?(?:简历)?(?:提出|准备|生成|设计)(?:一些|\d+\s*个|几个)?(?:简历)?(?:面试)?(?:问题|提问|追问|面试题)",
]

COLLECTION_QUANTIFIER_TERMS = {
    "每个人",
    "每个人的",
    "每位",
    "每位候选人",
    "各自",
    "分别",
    "所有人",
    "这些人",
    "这些候选人",
    "大家",
}


def extract_candidate_mentions(text: str, *, allow_full_text_fallback: bool = False) -> list[str]:
    """提取原始候选人指代，不扩展为规范姓名。"""
    value = str(text or "").strip()
    if not value:
        return []
    mentions: list[str] = []
    for pattern in _mention_patterns():
        for matched in re.finditer(pattern, value, re.IGNORECASE):
            mention = clean_candidate_mention(matched.group(1))
            if mention:
                mentions.append(mention)
    if not mentions and allow_full_text_fallback:
        mention = clean_candidate_mention(value)
        if mention and len(_normalize_key(mention)) <= 12:
            mentions.append(mention)
    return _dedupe(mentions)


def clean_candidate_mention(value: str) -> str:
    """清理候选人指代并返回。"""
    mention = str(value or "").strip(" ，,。；;:：?？")
    for prefix in (
        "请问",
        "帮我",
        "帮忙",
        "一下",
        "这里面的",
        "这里面",
        "其中的",
        "其中",
        "这些人里的",
        "这些人里",
        "以及",
        "并且",
        "同时",
        "还有",
        "这个",
        "这位",
        "候选人",
    ):
        if mention.startswith(prefix):
            mention = mention[len(prefix):].strip(" ，,。；;:：?？")
    if not mention or mention in {"谁", "他", "她", "他们", "她们", "人", "这个人", "刚才那个人", "这些人", "候选人"}:
        return ""
    mention_key = _normalize_key(mention).strip("的")
    if mention_key in {_normalize_key(term).strip("的") for term in COLLECTION_QUANTIFIER_TERMS}:
        return ""
    for prefix in ("分析", "判断", "评估"):
        if mention.startswith(prefix) and len(mention) > len(prefix):
            mention = mention[len(prefix):].strip(" ，,。；;:：?？")
    blocked_terms = {
        "领域",
        "岗位",
        "项目",
        "经验",
        "经历",
        "资料",
        "信息",
        "哪些",
        "多少",
        "都有谁",
        "谁",
        "候选人",
        "列举",
        "列出",
        "对方",
        "适合",
        "可能",
        "相关",
        "类似",
        "接近",
        "找出",
        "找找",
        "看看",
        "推荐",
        "这类",
    }
    blocked_terms.update(aliases_for_types("domain", "concept", "skill", "major"))
    if any(term in mention for term in blocked_terms):
        return ""
    return mention


def _normalize_key(value: str) -> str:
    """标准化键并返回。"""
    return re.sub(r"[\s_\-./,，。:：;；?？]+", "", str(value or "").lower())


def _mention_patterns() -> list[str]:
    """获取指代patterns并返回。"""
    taxonomy_terms = regex_terms_for_types("domain", "concept", "skill", "major")
    taxonomy_pattern = f"(?:{taxonomy_terms})" if taxonomy_terms else r"(?!x)x"
    return [pattern.replace("__TAXONOMY_TERMS__", taxonomy_pattern) for pattern in _MENTION_PATTERN_TEMPLATES]


def _dedupe(values: list[str]) -> list[str]:
    """去重结果并返回。"""
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
