"""shared_taxonomy 文件结构校验。"""

from __future__ import annotations

from pathlib import Path

from .common import yaml_mapping


def validate_taxonomy(taxonomy_dir: Path, errors: list[str]) -> None:
    """校验共享 taxonomy 的 domain/concept 文件存在且 entries 合法。"""
    domains_dir = taxonomy_dir / "domains"
    concepts_dir = taxonomy_dir / "concepts"
    domain_files = sorted(domains_dir.glob("*.yaml")) if domains_dir.exists() else []
    if not domain_files:
        errors.append(f"shared_taxonomy: missing domain yaml files under `{domains_dir}`")
    for path in domain_files:
        payload = yaml_mapping(path, errors)
        domain_name = str(payload.get("domain_name") or "").strip()
        aliases = payload.get("aliases")
        if not domain_name:
            errors.append(f"shared_taxonomy: `{path}` must declare domain_name")
        if not isinstance(aliases, list) or not aliases:
            errors.append(f"shared_taxonomy: `{path}` must declare non-empty aliases")
        for index, entry_raw in enumerate(list(payload.get("local_concepts", []) or [])):
            entry = dict(entry_raw or {})
            canonical = str(entry.get("name") or "").strip()
            entry_type = str(entry.get("type") or "").strip()
            if not canonical:
                errors.append(f"shared_taxonomy: `{path}` local_concepts[{index}] missing name")
            if entry_type not in {"domain", "concept", "skill", "major"}:
                errors.append(f"shared_taxonomy: `{path}` local_concepts[{index}] has unsupported type `{entry_type}`")
    global_path = concepts_dir / "global.yaml"
    if not global_path.exists():
        errors.append(f"shared_taxonomy: missing `{global_path}`")
    else:
        payload = yaml_mapping(global_path, errors)
        concepts = payload.get("concepts")
        if not isinstance(concepts, list):
            errors.append(f"shared_taxonomy: `{global_path}` must declare concepts")
        for index, entry_raw in enumerate(list(concepts or [])):
            entry = dict(entry_raw or {})
            if not str(entry.get("name") or "").strip():
                errors.append(f"shared_taxonomy: `{global_path}` concepts[{index}] missing name")
            if str(entry.get("type") or "").strip() not in {"concept", "skill", "major"}:
                errors.append(f"shared_taxonomy: `{global_path}` concepts[{index}] has unsupported type `{entry.get('type')}`")
