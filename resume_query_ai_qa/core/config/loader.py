"""YAML/env configuration loading entrypoint.

这个文件负责什么：
  读取 configs/*.yaml，构造 ResumeQAConfig，并触发启动期结构校验。

应该从哪个函数读起：
  load_config() -> load_yaml()。

不会负责什么：
  不解释业务规则，不做 node 决策，不吞掉坏配置错误。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from resume_query_ai_qa.core.config_validation import validate_config_structure

from .compiler_flags import load_project_env
from .model import ResumeQAConfig


def load_config(configs_dir: Path | None = None) -> ResumeQAConfig:
    """读取所有 QA runtime YAML 并执行结构校验；不承载业务决策。"""
    app_root = Path(__file__).resolve().parents[2]
    config_dir = Path(configs_dir or app_root / "configs")
    cfg = ResumeQAConfig(
        app_root=app_root,
        configs_dir=config_dir,
        taxonomy_dir=app_root.parent / "shared_taxonomy",
        intents=load_yaml(config_dir / "intents.yaml"),
        scenarios=load_yaml(config_dir / "scenarios.yaml"),
        tool_policy=load_yaml(config_dir / "tool_policy.yaml"),
        jd_scoring=load_yaml(config_dir / "jd_scoring.yaml"),
        evidence_policy=load_yaml(config_dir / "evidence_policy.yaml"),
        validation=load_yaml(config_dir / "validation.yaml"),
        llm=load_yaml(config_dir / "llm.yaml"),
        router_rules=load_yaml(config_dir / "router_rules.yaml"),
        compiler_templates=load_yaml(config_dir / "compiler_templates.yaml"),
        answer_layouts=load_yaml(config_dir / "answer_layouts.yaml"),
        aggregator_tasks=load_yaml(config_dir / "aggregator_tasks.yaml"),
        condition_rules=load_yaml(config_dir / "condition_rules.yaml"),
    )
    validate_config_structure(cfg)
    load_project_env(cfg)
    return cfg


def load_yaml(path: Path) -> Dict[str, Any]:
    """读取单个 YAML 并要求顶层为 mapping，坏配置在启动期显式失败。"""
    if not path.exists():
        raise FileNotFoundError(f"missing QA config: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"QA config must be a mapping: {path}")
    return payload
