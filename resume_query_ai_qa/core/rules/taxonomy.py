"""Shared taxonomy access for Query-AI rules and tools."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from resume_query_ai_qa.core.config import load_config


@dataclass(frozen=True)
class TaxonomyEntry:
    """一条共享分类事实，包含标准值、别名和召回扩展词。"""
    type: str
    value: str
    aliases: tuple[str, ...]
    retrieval_terms: tuple[str, ...]


def taxonomy_entries() -> tuple[TaxonomyEntry, ...]:
    """返回 ``shared_taxonomy`` 中的全部共享分类条目。"""
    return _taxonomy_entries_for_dir(load_config().taxonomy_dir)


def entries_by_type(*types: str) -> tuple[TaxonomyEntry, ...]:
    """按类型整理条目集合并返回。"""
    wanted = {str(item) for item in types if str(item).strip()}
    if not wanted:
        return taxonomy_entries()
    return tuple(entry for entry in taxonomy_entries() if entry.type in wanted)


def aliases_for_types(*types: str) -> list[str]:
    """根据类型集合生成别名集合并返回。"""
    return _dedupe_terms(alias for entry in entries_by_type(*types) for alias in entry.aliases)


def retrieval_terms_for_types(*types: str) -> list[str]:
    """根据类型集合生成检索词项集合并返回。"""
    return _dedupe_terms(term for entry in entries_by_type(*types) for term in entry.retrieval_terms)


def taxonomy_entry_types(value: str) -> set[str]:
    """获取分类体系条目类型集合并返回。"""
    key = normalize_taxonomy_key(value)
    if not key:
        return set()
    output: set[str] = set()
    for entry in taxonomy_entries():
        keys = {normalize_taxonomy_key(entry.value), *(normalize_taxonomy_key(alias) for alias in entry.aliases)}
        if key in keys:
            output.add(entry.type)
    return output


def match_taxonomy(raw_value: str, preferred_types: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """匹配结果分类体系并返回匹配结果。"""
    raw_key = normalize_taxonomy_key(raw_value)
    if not raw_key:
        return []
    preferred = {str(item) for item in list(preferred_types or []) if str(item).strip()}
    exact: list[dict[str, Any]] = []
    contains: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []
    for entry in taxonomy_entries():
        if preferred and entry.type not in preferred:
            continue
        alias_keys = [normalize_taxonomy_key(alias) for alias in entry.aliases if alias]
        if raw_key in alias_keys:
            exact.append(_match_payload(entry, "exact", 1.0))
            continue
        if any(key and (key in raw_key or raw_key in key) for key in alias_keys):
            contains.append(_match_payload(entry, "contains", 0.95))
            continue
        best = max((SequenceMatcher(None, raw_key, key).ratio() for key in alias_keys if key), default=0.0)
        if best >= 0.82:
            fuzzy.append(_match_payload(entry, "fuzzy", round(best, 3)))
    return _dedupe_matches(exact or contains or fuzzy)


def expand_query_terms(query: str, *, types: Iterable[str] | None = None) -> list[str]:
    """使用匹配分类条目的检索别名扩展查询词。"""
    raw_terms = split_terms(query)
    terms: list[str] = list(raw_terms)
    normalized_query = normalize_taxonomy_key(query)
    if not normalized_query:
        return terms
    for entry in entries_by_type(*list(types or [])):
        alias_keys = [normalize_taxonomy_key(alias) for alias in entry.aliases if alias]
        if any(key and key in normalized_query for key in alias_keys):
            terms.extend(entry.retrieval_terms)
    return _dedupe_terms(terms)


def regex_terms_for_types(*types: str) -> str:
    """根据类型集合生成regex词项集合并返回。"""
    terms = aliases_for_types(*types)
    if not terms:
        return ""
    return "|".join(re.escape(item) for item in sorted(terms, key=len, reverse=True))


def split_terms(text: str) -> list[str]:
    """拆分词项集合并返回。"""
    return [item for item in re.split(r"[\s,，;；/]+", str(text or "")) if item.strip()]


def normalize_taxonomy_key(value: str) -> str:
    """标准化分类体系键并返回。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s_\-./,，。:：;；?？]+", "", normalized)


@lru_cache(maxsize=4)
def _taxonomy_entries_for_dir(taxonomy_dir: Path) -> tuple[TaxonomyEntry, ...]:
    """根据DIR生成分类体系条目集合并返回。"""
    entries: list[TaxonomyEntry] = []
    for path in sorted((taxonomy_dir / "domains").glob("*.yaml")):
        payload = _read_yaml(path)
        name = str(payload.get("domain_name", "") or "").strip()
        if not name:
            continue
        aliases = _strings([name, *list(payload.get("aliases", []) or [])])
        retrieval_terms = _strings([*aliases, *list(payload.get("search_hints", []) or [])])
        entries.append(TaxonomyEntry("domain", name, tuple(_dedupe_terms(aliases)), tuple(_dedupe_terms(retrieval_terms))))
        for concept in _strings(payload.get("concepts", []) or []):
            entries.append(TaxonomyEntry("concept", concept, (concept,), (concept,)))
        for item in list(payload.get("local_concepts", []) or []):
            if not isinstance(item, dict):
                continue
            concept_name = str(item.get("name", "") or "").strip()
            if not concept_name:
                continue
            concept_aliases = _strings([concept_name, *list(item.get("aliases", []) or [])])
            entries.append(TaxonomyEntry(str(item.get("type", "concept") or "concept"), concept_name, tuple(concept_aliases), tuple(concept_aliases)))
    global_payload = _read_yaml(taxonomy_dir / "concepts" / "global.yaml")
    for item in list(global_payload.get("concepts", []) or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        aliases = _strings([name, *list(item.get("aliases", []) or [])])
        entries.append(TaxonomyEntry(str(item.get("type", "concept") or "concept"), name, tuple(aliases), tuple(aliases)))
    return tuple(entries)


def _read_yaml(path: Path) -> dict[str, Any]:
    """读取yaml并返回。"""
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _strings(values: Iterable[Any]) -> list[str]:
    """获取字符串集合并返回。"""
    return [str(item).strip() for item in values if str(item).strip()]


def _match_payload(entry: TaxonomyEntry, matched_by: str, confidence: float) -> dict[str, Any]:
    """匹配结果载荷并返回匹配结果。"""
    return {
        "type": entry.type,
        "value": entry.value,
        "matched_by": matched_by,
        "confidence": confidence,
        "retrieval_terms": list(entry.retrieval_terms),
    }


def _dedupe_terms(values: Iterable[str]) -> list[str]:
    """去重词项集合并返回。"""
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        key = normalize_taxonomy_key(item)
        if not item or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _dedupe_matches(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按分类匹配键去重并返回匹配结果。"""
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (str(value.get("type", "")), str(value.get("value", "")))
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output
