"""Configuration structure validation orchestrator.

这个文件负责什么：
  编排所有 YAML/shared_taxonomy 的启动期结构校验。

应该从哪个函数读起：
  validate_config_structure()。

不会负责什么：
  不执行 graph，不修复配置，不做运行时 validator 的工作。
"""

from __future__ import annotations

from typing import Any

from .answer_rules import validate_aggregator_tasks, validate_answer_layouts
from .compiler_templates import validate_compiler_templates
from .condition_validation import validate_condition_rules, validate_validation_rules
from .scenarios import scenario_pairs, validate_router_rules, validate_scenarios
from .taxonomy_validation import validate_taxonomy
from .tool_policy import validate_intent_tools, validate_tool_metadata


class ConfigStructureError(ValueError):
    """配置结构错误；由 load_config 在启动期抛出，避免坏规则进入运行时。"""


def validate_config_structure(config: Any) -> None:
    """编排所有 YAML 和 shared_taxonomy 的结构校验，不承载业务节点逻辑。"""
    errors: list[str] = []
    intents = set(dict(config.intents.get("intents", {}) or {}))
    scenarios = set(dict(config.scenarios.get("scenarios", {}) or {}))
    tools = set(dict(config.tool_policy.get("tools", {}) or {}))
    allowed_pairs = scenario_pairs(config.scenarios)

    validate_scenarios(config.scenarios, intents, errors)
    validate_router_rules(config.router_rules, intents, errors)
    validate_intent_tools(config.tool_policy, intents, scenarios, allowed_pairs, tools, errors)
    validate_tool_metadata(config.tool_policy, intents, tools, errors)
    validate_compiler_templates(config.compiler_templates, intents, scenarios, allowed_pairs, tools, errors)
    validate_answer_layouts(config.answer_layouts, tools, errors)
    validate_aggregator_tasks(config.aggregator_tasks, tools, errors)
    validate_condition_rules(config.condition_rules, errors)
    validate_validation_rules(config.validation, errors)
    validate_taxonomy(config.taxonomy_dir, errors)

    if errors:
        raise ConfigStructureError("Invalid QA config structure:\n- " + "\n- ".join(errors))
