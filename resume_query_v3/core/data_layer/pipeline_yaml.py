from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml


@dataclass(frozen=True)
class SectionAliasConfig:
    work_sections: List[str]
    education_sections: List[str]
    skill_sections: List[str]
    project_sections: List[str]
    summary_sections: List[str]


@dataclass(frozen=True)
class DomainConfig:
    domain_name: str
    aliases: List[str]
    concepts: List[str]
    search_hints: List[str]
    local_concepts: Dict[str, Dict[str, Any]]


@dataclass(frozen=True)
class RoutingConfig:
    oversized_block_count: int
    oversized_token_budget: int
    dense_block_count: int
    dense_avg_block_length: int
    messy_min_section_hit_rate: float
    messy_duplicate_ratio: float
    low_ocr_noise_ratio: float
    mixed_language_ratio: float


@dataclass(frozen=True)
class ChunkingConfig:
    hard_drop_patterns: List[str]
    soft_downgrade_patterns: List[str]
    keep_keywords: List[str]
    mandatory_sections: List[str]
    oversized_block_budget: int
    dense_block_budget: int
    standard_block_budget: int
    project_cleanup: Dict[str, Any]


@dataclass(frozen=True)
class ValidateConfig:
    min_field_confidence: float
    min_chunk_confidence: float
    min_tag_confidence: float
    require_evidence: bool


def load_section_aliases(path: Path) -> SectionAliasConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SectionAliasConfig(
        work_sections=_string_list(payload.get("work_sections")),
        education_sections=_string_list(payload.get("education_sections")),
        skill_sections=_string_list(payload.get("skill_sections")),
        project_sections=_string_list(payload.get("project_sections")),
        summary_sections=_string_list(payload.get("summary_sections")),
    )


def load_concepts(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _parse_concepts_payload(payload)


def load_domain_configs(directory: Path) -> Dict[str, DomainConfig]:
    configs: Dict[str, DomainConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        domain_name = str(payload.get("domain_name", "")).strip()
        if not domain_name:
            continue
        configs[domain_name] = DomainConfig(
            domain_name=domain_name,
            aliases=_string_list(payload.get("aliases")),
            concepts=_string_list(payload.get("concepts")),
            search_hints=_string_list(payload.get("search_hints")),
            local_concepts=_parse_concepts_payload({"concepts": payload.get("local_concepts", []) or []}),
        )
    return configs


def merge_global_and_domain_local_concepts(
    global_concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, DomainConfig],
) -> Dict[str, Dict[str, Any]]:
    merged = {name: dict(entry) for name, entry in global_concepts.items()}
    for domain in domains.values():
        for name, entry in domain.local_concepts.items():
            merged[name] = dict(entry)
    return merged


def load_routing_config(path: Path) -> RoutingConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RoutingConfig(
        oversized_block_count=int(payload.get("oversized_block_count", 60) or 60),
        oversized_token_budget=int(payload.get("oversized_token_budget", 4800) or 4800),
        dense_block_count=int(payload.get("dense_block_count", 32) or 32),
        dense_avg_block_length=int(payload.get("dense_avg_block_length", 48) or 48),
        messy_min_section_hit_rate=float(payload.get("messy_min_section_hit_rate", 0.08) or 0.08),
        messy_duplicate_ratio=float(payload.get("messy_duplicate_ratio", 0.18) or 0.18),
        low_ocr_noise_ratio=float(payload.get("low_ocr_noise_ratio", 0.28) or 0.28),
        mixed_language_ratio=float(payload.get("mixed_language_ratio", 0.25) or 0.25),
    )


def load_chunking_config(path: Path) -> ChunkingConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ChunkingConfig(
        hard_drop_patterns=_string_list(payload.get("hard_drop_patterns")),
        soft_downgrade_patterns=_string_list(payload.get("soft_downgrade_patterns")),
        keep_keywords=_string_list(payload.get("keep_keywords")),
        mandatory_sections=_string_list(payload.get("mandatory_sections")),
        oversized_block_budget=int(payload.get("oversized_block_budget", 26) or 26),
        dense_block_budget=int(payload.get("dense_block_budget", 24) or 24),
        standard_block_budget=int(payload.get("standard_block_budget", 28) or 28),
        project_cleanup=dict(payload.get("project_cleanup", {}) or {}),
    )


def load_validate_config(path: Path) -> ValidateConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ValidateConfig(
        min_field_confidence=float(payload.get("min_field_confidence", 0.45) or 0.45),
        min_chunk_confidence=float(payload.get("min_chunk_confidence", 0.4) or 0.4),
        min_tag_confidence=float(payload.get("min_tag_confidence", 0.45) or 0.45),
        require_evidence=bool(payload.get("require_evidence", True)),
    )


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_concepts_payload(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    concepts: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("concepts", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        concepts[name] = {
            "name": name,
            "type": str(item.get("type", "")).strip(),
            "aliases": _string_list(item.get("aliases")),
        }
    return concepts
