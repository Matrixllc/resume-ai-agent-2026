"""Candidate reference and pronoun resolution tools.

这个文件负责什么：
  把“第一名/这些人/刚才那个人/某个姓名”等文本引用解析为 candidate ids。

应该从哪个函数读起：
  resolve_candidate_reference()。

不会负责什么：
  不查画像、不排序、不比较、不生成答案；只解析候选人引用。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List

from resume_query_ai_qa.core.inspection.result_inspection import normalize_string_list
from resume_query_ai_qa.core.rules.candidate_mentions import extract_candidate_mentions
from resume_query_ai_qa.core.schemas import CandidateBrief

from .candidate_tools import list_all_candidates
from .common import dedupe_ids, normalize_key


def resolve_candidate_reference(
    text: str,
    session_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """把姓名、代词、排名引用解析成 candidate ids。

    典型输入：
    - 明确姓名：`孟连星`
    - 上下文代词：`他`、`这个人`
    - 候选池：`这些人`
    - 排名结果：`第一名`

    数据来源：候选人列表 + session_context。返回 resolved/needs_clarification
    和 candidate_ids。边界：不查画像、不比较、不排序、不生成答案。
    """
    context = session_context or {}
    pool_ids = normalize_string_list(context.get("last_candidate_pool_ids", []))
    uses_pool_context = any(token in text for token in ["这里面", "其中", "这些人", "这些候选人", "这批人", "这几个人"])
    if uses_pool_context and pool_ids:
        pool_keys = {normalize_key(item) for item in pool_ids}
        candidates = [item for item in list_all_candidates() if normalize_key(item.resume_identity) in pool_keys]
    else:
        candidates = list_all_candidates()
    normalized_text = normalize_key(text)
    direct_matches = [
        item
        for item in candidates
        if normalize_key(item.resume_identity) in normalized_text
        or any(len(alias) >= 2 and alias in normalized_text for alias in _candidate_aliases(item))
    ]
    ranked_ids = normalize_string_list(context.get("last_ranking_candidate_ids", []))
    focused_id = str(context.get("last_candidate_id", "") or "").strip()
    comparison_ids = normalize_string_list(context.get("last_comparison_candidate_ids", []))
    direct_ids = [item.resume_identity for item in direct_matches]
    if len(direct_matches) > 1 and _looks_like_multi_profile_request(text):
        return {
            "resolved": True,
            "needs_clarification": False,
            "candidate_ids": direct_ids,
            "source": "multi_direct_profile_match",
            "match_candidates": _match_candidate_payloads(direct_matches, score=1.0, matched_by="direct_match"),
        }
    if direct_ids and "这个人" in text:
        return {
            "resolved": len(direct_ids) == 1,
            "needs_clarification": len(direct_ids) != 1,
            "candidate_ids": direct_ids,
            "source": "direct_match_with_local_pronoun" if len(direct_ids) == 1 else "ambiguous_direct_match_with_local_pronoun",
            **({"match_candidates": _match_candidate_payloads(direct_matches, score=1.0, matched_by="direct_match")} if len(direct_ids) != 1 else {}),
        }
    if direct_ids and focused_id and any(token in text for token in ["刚才那个人", "他", "她", "这个人"]):
        candidate_ids = dedupe_ids([focused_id] + direct_ids)
        if len(candidate_ids) >= 2:
            return {
                "resolved": True,
                "needs_clarification": False,
                "candidate_ids": candidate_ids,
                "source": "direct_plus_last_candidate",
            }
    if direct_ids and ranked_ids and any(token in text for token in ["第一", "第一名", "刚才第一位"]):
        candidate_ids = dedupe_ids([ranked_ids[0]] + direct_ids)
        if len(candidate_ids) >= 2:
            return {
                "resolved": True,
                "needs_clarification": False,
                "candidate_ids": candidate_ids,
                "source": "direct_plus_last_ranking_first",
            }
    if len(direct_matches) == 1:
        return {
            "resolved": True,
            "needs_clarification": False,
            "candidate_ids": [direct_matches[0].resume_identity],
            "source": "direct_match",
        }
    if len(direct_matches) > 1:
        return {
            "resolved": False,
            "needs_clarification": True,
            "candidate_ids": [item.resume_identity for item in direct_matches],
            "source": "ambiguous_direct_match",
            "match_candidates": _match_candidate_payloads(direct_matches, score=1.0, matched_by="direct_match"),
        }

    fuzzy_matches = _fuzzy_candidate_matches(text, candidates)
    if fuzzy_matches:
        top_score = fuzzy_matches[0]["score"]
        close_matches = [item for item in fuzzy_matches if top_score - item["score"] <= 0.08]
        if (top_score >= 0.8 or str(fuzzy_matches[0].get("matched_by")) == "fuzzy_short_name_ratio_match") and len(close_matches) == 1:
            return {
                "resolved": True,
                "needs_clarification": False,
                "candidate_ids": [str(fuzzy_matches[0]["resume_identity"])],
                "source": str(fuzzy_matches[0]["matched_by"]),
                "match_candidates": fuzzy_matches[:5],
            }
        return {
            "resolved": False,
            "needs_clarification": True,
            "candidate_ids": [str(item["resume_identity"]) for item in fuzzy_matches[:5]],
            "source": "ambiguous_fuzzy_match" if len(close_matches) > 1 else "low_confidence_fuzzy_match",
            "match_candidates": fuzzy_matches[:5],
        }

    if uses_pool_context:
        return {
            "resolved": False,
            "needs_clarification": True,
            "candidate_ids": [],
            "source": "unresolved_in_candidate_pool",
        }

    if ranked_ids and ("第一" in text or "第一名" in text):
        return {
            "resolved": True,
            "needs_clarification": False,
            "candidate_ids": [ranked_ids[0]],
            "source": "last_ranking_first",
        }
    if focused_id and any(token in text for token in ["刚才那个人", "他", "她", "这个人"]):
        return {
            "resolved": True,
            "needs_clarification": False,
            "candidate_ids": [focused_id],
            "source": "last_candidate",
        }
    if comparison_ids and any(token in text for token in ["他们", "这两个人", "两个人"]):
        return {
            "resolved": True,
            "needs_clarification": False,
            "candidate_ids": comparison_ids,
            "source": "last_comparison",
        }
    return {
        "resolved": False,
        "needs_clarification": True,
        "candidate_ids": [],
        "source": "unresolved",
    }


def _looks_like_multi_profile_request(text: str) -> bool:
    """判断文本是否像多个候选人的画像/经历展示请求。"""
    return any(token in str(text or "") for token in ["个人信息", "信息展示", "展示", "显示", "介绍", "资料", "经历", "背景", "profile"])


def _candidate_aliases(candidate: CandidateBrief) -> List[str]:
    """生成候选人的 ID、姓名、短名、拼音等可匹配别名。"""
    name = str(candidate.name or "").strip()
    aliases = {candidate.resume_identity, name}
    if 2 <= len(name) <= 4 and not re.search(r"[A-Za-z\s]", name):
        aliases.add(name[1:])
        aliases.add(name[-2:])
        aliases.update(_pinyin_aliases(name))
    name_parts = [part for part in re.split(r"[\s._-]+", name) if part]
    if len(name_parts) >= 2 and all(re.fullmatch(r"[A-Za-z]+", part) for part in name_parts):
        aliases.update(name_parts)
        aliases.add("".join(name_parts))
        aliases.add(" ".join(reversed(name_parts)))
        aliases.add("".join(reversed(name_parts)))
    return [normalize_key(alias) for alias in aliases if str(alias).strip()]

def _fuzzy_candidate_matches(text: str, candidates: List[CandidateBrief]) -> List[Dict[str, Any]]:
    """根据候选人提及词，对候选人列表做模糊匹配并按置信度排序。"""
    mentions = _candidate_reference_mentions(text)
    if not mentions:
        return []
    matches: List[Dict[str, Any]] = []
    for candidate in candidates:
        best_score = 0.0
        best_by = ""
        best_mention = ""
        for mention in mentions:
            score, matched_by = _candidate_match_score(mention, candidate)
            if score > best_score:
                best_score = score
                best_by = matched_by
                best_mention = mention
        if best_score >= 0.55:
            matches.append(
                {
                    "resume_identity": candidate.resume_identity,
                    "name": candidate.name,
                    "score": round(best_score, 3),
                    "matched_by": best_by,
                    "mention": best_mention,
                }
            )
    return sorted(matches, key=lambda item: (-float(item["score"]), str(item.get("name", "")), str(item.get("resume_identity", ""))))

def _candidate_reference_mentions(text: str) -> List[str]:
    """从文本中抽取可能指向候选人的提及词。"""
    return extract_candidate_mentions(text, allow_full_text_fallback=True)

def _candidate_match_score(mention: str, candidate: CandidateBrief) -> tuple[float, str]:
    """计算单个提及词和候选人的匹配分数及匹配方式。"""
    mention_key = normalize_key(mention)
    name_key = normalize_key(candidate.name)
    if not mention_key or not name_key:
        return 0.0, ""
    if mention_key == name_key:
        return 1.0, "exact_name_match"
    aliases = _candidate_aliases(candidate)
    if mention_key in aliases:
        return 0.98, "exact_alias_match"
    if len(mention_key) == 1:
        if name_key.endswith(mention_key):
            return 0.82, "fuzzy_suffix_match"
        if mention_key in name_key:
            return 0.74, "fuzzy_contains_match"
        return 0.0, ""
    if name_key.endswith(mention_key) or any(alias.endswith(mention_key) for alias in aliases):
        return 0.9, "fuzzy_suffix_match"
    if mention_key in name_key or any(mention_key in alias for alias in aliases):
        return 0.84, "fuzzy_contains_match"
    best_ratio = max([SequenceMatcher(None, mention_key, name_key).ratio(), *[SequenceMatcher(None, mention_key, alias).ratio() for alias in aliases]], default=0.0)
    if (
        len(mention_key) == len(name_key)
        and 2 <= len(mention_key) <= 4
        and not re.search(r"[a-z]", mention_key + name_key)
        and best_ratio >= 0.66
    ):
        return best_ratio, "fuzzy_short_name_ratio_match"
    if best_ratio >= 0.82:
        return best_ratio, "fuzzy_ratio_match"
    return 0.0, ""

def _match_candidate_payloads(candidates: List[CandidateBrief], *, score: float, matched_by: str) -> List[Dict[str, Any]]:
    """把候选人对象转成 clarification/debug 可展示的匹配候选列表。"""
    return [
        {
            "resume_identity": candidate.resume_identity,
            "name": candidate.name,
            "score": score,
            "matched_by": matched_by,
        }
        for candidate in candidates
    ]

def _pinyin_aliases(name: str) -> List[str]:
    """为中文姓名生成拼音、名在前等别名，提升模糊解析召回。"""
    try:
        from pypinyin import lazy_pinyin  # type: ignore
    except Exception:
        parts = [_PINYIN_FALLBACK_BY_CHAR.get(char, "") for char in name]
        parts = [part for part in parts if part]
        if len(parts) != len(name):
            return []
    else:
        parts = [part for part in lazy_pinyin(name) if str(part).strip()]
    if not parts:
        return []
    aliases = {" ".join(parts), "".join(parts)}
    if len(parts) >= 2:
        given = parts[1:]
        family = parts[:1]
        aliases.update(
            {
                " ".join(given),
                "".join(given),
                " ".join([*given, *family]),
                "".join([*given, *family]),
            }
        )
    return list(aliases)

_PINYIN_FALLBACK_BY_CHAR = {
    "孟": "meng",
    "连": "lian",
    "星": "xing",
    "孔": "kong",
    "德": "de",
    "程": "cheng",
    "张": "zhang",
    "英": "ying",
    "杰": "jie",
}

def clean_retrieval_query(query: str) -> str:
    """清理检索查询并返回。"""
    text = str(query or "").strip()
    text = re.sub(r"^(刚才|上面|上一次|之前|前面)(说到|提到|聊到|那位|那个)?", "", text).strip()
    for candidate in list_all_candidates():
        for alias in sorted(_candidate_aliases(candidate), key=len, reverse=True):
            if alias:
                text = re.sub(re.escape(alias), " ", text, flags=re.IGNORECASE)
    noise_tokens = [
        "请问",
        "帮我",
        "帮忙",
        "一下",
        "看下",
        "看一下",
        "有哪些",
        "都有谁",
        "候选人",
        "相关",
        "信息",
        "资料",
        "介绍",
        "显示",
        "展示",
        "体现在哪里",
        "体现在哪",
        "哪里体现",
        "项目有哪些",
        "项目",
        "的",
        "?",
        "？",
    ]
    for token in noise_tokens:
        text = text.replace(token, " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text
