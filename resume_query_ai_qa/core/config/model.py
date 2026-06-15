"""QA configuration facade and runtime query methods.

这个文件负责什么：
  保存所有 YAML 原始配置，并提供跨节点共享的查询方法。

应该从哪个函数读起：
  ResumeQAConfig，然后按 node 需要阅读 allowed_tools_for_intent、
  semantic_defaults_for_intent、tool_produces 等查询方法。

不会负责什么：
  不读取文件，不执行节点逻辑，不判断用户问题，不修复配置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field

from .compiler_flags import compiler_flags_for_config
from .tool_hints import normalize_tool_hints


class ResumeQAConfig(BaseModel):
    """跨节点共享的配置模型；只提供规则查询，不读取文件、不调用 nodes/tools。"""

    app_root: Path
    configs_dir: Path
    taxonomy_dir: Path
    intents: Dict[str, Any] = Field(default_factory=dict)
    scenarios: Dict[str, Any] = Field(default_factory=dict)
    tool_policy: Dict[str, Any] = Field(default_factory=dict)
    jd_scoring: Dict[str, Any] = Field(default_factory=dict)
    evidence_policy: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    llm: Dict[str, Any] = Field(default_factory=dict)
    router_rules: Dict[str, Any] = Field(default_factory=dict)
    compiler_templates: Dict[str, Any] = Field(default_factory=dict)
    answer_layouts: Dict[str, Any] = Field(default_factory=dict)
    aggregator_tasks: Dict[str, Any] = Field(default_factory=dict)
    condition_rules: Dict[str, Any] = Field(default_factory=dict)

    def compiler_flags(self) -> Dict[str, Any]:
        """返回 compiler 模式开关；env 校验集中在 config 层，不下沉到 compiler 节点。"""
        return compiler_flags_for_config(self)

    def allowed_tools_for_intent(self, intent: str, scenario: str = "") -> list[str]:
        """按 intent/scenario 查询允许工具，供 planner/compiler/validator 共享同一 tool_policy。"""
        entry = self._intent_tool_entry(intent)
        scoped = self._scenario_tool_entry(entry, scenario)
        if "allowed_tools" in scoped:
            return [str(item) for item in list(scoped.get("allowed_tools", []) or [])]
        return [str(item) for item in list(entry.get("allowed_tools", []) or [])]

    def semantic_needs_for_intent(self, intent: str) -> list[str]:
        """读取 intent 默认 semantic_needs；只暴露配置结果，不推断用户问题。"""
        entry = self._intent_entry(intent)
        return [str(item) for item in list(entry.get("semantic_needs", []) or [])]

    def scenario_names(self) -> set[str]:
        """返回所有 canonical scenario 名称，供 router/validator 做合法性检查。"""
        return set(dict(self.scenarios.get("scenarios", {}) or {}))

    def allowed_scenarios_for_intent(self, intent: str) -> list[str]:
        """返回某 intent 允许的 scenario，scenario 判定仍由 router/finalizer 负责。"""
        return [
            str(name)
            for name, raw in dict(self.scenarios.get("scenarios", {}) or {}).items()
            if intent in {str(item) for item in list(dict(raw or {}).get("allowed_intents", []) or [])}
        ]

    def scenario_catalog_for_router(self) -> dict[str, Any]:
        """把 scenarios.yaml 的 catalog 交给 router 使用，不在 config 层做判定。"""
        return dict(self.scenarios.get("scenarios", {}) or {})

    def scenario_resolution_rule(self, intent: str) -> dict[str, str]:
        """返回规则路由器使用的 scenario 决策表，运行时不再硬编码 intent 分支。"""
        rules = dict(self.scenarios.get("resolution_rules", {}) or {})
        return {str(key): str(value) for key, value in dict(rules.get(intent, {}) or {}).items() if str(value).strip()}

    def planner_for_scenarios(self, scenarios: dict[str, str]) -> str:
        """根据 scenario 元数据选择 generic planner，任一场景要求 LLM 时使用 LLM。"""
        catalog = self.scenario_catalog_for_router()
        planners = {
            str(dict(catalog.get(scenario, {}) or {}).get("planner", "rule") or "rule")
            for scenario in scenarios.values()
        }
        return "llm" if "llm" in planners else "rule"

    def optional_semantic_needs_for_intent(self, intent: str, scenario: str = "") -> list[str]:
        """读取 scenario 级可选语义需求，供 planner/compiler 对齐同一 intent 规则。"""
        entry = self._intent_entry(intent)
        optional = dict(entry.get("scenario_optional_needs", {}) or {})
        return [str(item) for item in list(optional.get(str(scenario or "").strip(), []) or [])]

    def tool_capabilities_for_intent(self, intent: str, scenario: str = "") -> list[dict[str, str]]:
        """给 LLM planner 暴露工具名和描述；不绕过 allowed_tools 的白名单。"""
        tools = dict(self.tool_policy.get("tools", {}) or {})
        return [
            {
                "name": name,
                "description": str(dict(tools.get(name, {}) or {}).get("description", "") or ""),
            }
            for name in self.allowed_tools_for_intent(intent, scenario)
        ]

    def preferred_tools_for_scenario(self, intent: str, scenario: str = "") -> list[str]:
        """查询首选工具；compiler 仍需按 allowed/forbidden 和 registry 再约束。"""
        entry = self._intent_tool_entry(intent)
        scoped = self._scenario_tool_entry(entry, scenario)
        if scoped:
            return [str(item) for item in list(scoped.get("preferred_tools", []) or [])]
        return [str(item) for item in list(entry.get("preferred_tools", []) or [])]

    def preferred_tool_hints_for_scenario(self, intent: str, scenario: str = "") -> list[dict[str, Any]]:
        """查询工具 hint 并归一化；hint 只是建议，不是可执行 ToolCallSpec。"""
        entry = self._intent_tool_entry(intent)
        scoped = self._scenario_tool_entry(entry, scenario)
        if "preferred_tool_hints" in scoped:
            return normalize_tool_hints(scoped.get("preferred_tool_hints"))
        if "preferred_tool_hints" in entry:
            return normalize_tool_hints(entry.get("preferred_tool_hints"))
        return [{"name": name, "confidence": 0.75} for name in self.preferred_tools_for_scenario(intent, scenario)]

    def semantic_defaults_for_intent(self, intent: str, scenario: str = "") -> dict[str, bool]:
        """读取 requires_jd/requires_evidence 默认值，供 router finalizer 和 planner 对齐。"""
        entry = self._intent_entry(intent)
        scenarios = dict(entry.get("scenario_defaults", {}) or {})
        scoped = dict(scenarios.get(str(scenario or "").strip(), {}) or {})
        return {
            "requires_jd": bool(scoped.get("requires_jd_criteria", entry.get("requires_jd_criteria", False))),
            "requires_evidence": bool(scoped.get("requires_evidence", entry.get("requires_evidence", False))),
        }

    def forbidden_tools_for_scenario(self, intent: str, scenario: str = "") -> list[str]:
        """查询禁用工具；用于 compiler/validator/repair 共用同一禁止策略。"""
        entry = self._intent_tool_entry(intent)
        scoped = self._scenario_tool_entry(entry, scenario)
        if scoped:
            return [str(item) for item in list(scoped.get("forbidden_tools", []) or [])]
        return [str(item) for item in list(entry.get("forbidden_tools", []) or [])]

    def retry_limit(self, name: str, default: int = 0) -> int:
        """读取 validator/repair 重试次数，避免节点各自硬编码 retry。"""
        limits = dict(self.validation.get("retry_limits", {}) or {})
        return int(limits.get(name, default) or 0)

    def aggregator_task_rules(self) -> dict[str, Any]:
        """返回 answer 聚合任务规则，aggregator 只消费不私有维护任务表。"""
        return dict(self.aggregator_tasks.get("task_types", {}) or {})

    def answer_layout_rules(self) -> dict[str, Any]:
        """返回答案 layout 规则，renderer/validator 共用同一 answer_layouts。"""
        return dict(self.answer_layouts.get("layouts", {}) or {})

    def tools_with_role(self, role: str) -> list[str]:
        """按 tool role 查询工具，供 plan_building/source_policy 等公共规则复用。"""
        return [
            str(name)
            for name, raw in dict(self.tool_policy.get("tools", {}) or {}).items()
            if role in {str(item) for item in list(dict(raw or {}).get("roles", []) or [])}
        ]

    def default_output_key(self, tool_name: str) -> str:
        """查询工具默认产物 key；compiler/validator 不各自猜 output_key。"""
        tool = self._tool_entry(tool_name)
        return str(tool.get("default_output_key") or f"{tool_name}_result")

    def tool_produces(self, tool_name: str) -> list[str]:
        """读取工具声明的产物类型，供 compiler、inspection 和 validator 共用同一份 metadata。"""
        tool = self._tool_entry(tool_name)
        return [str(item) for item in list(tool.get("produces", []) or []) if str(item).strip()]

    def tool_primary_artifact_type(self, tool_name: str) -> str:
        """返回可进入 QueryPlan artifact binding 的首个产物类型；其他产物仍保留在工具 metadata 中。"""
        if not self.tool_binds_primary_artifact(tool_name):
            return ""
        supported = {
            "candidate_collection",
            "candidate_count",
            "candidate_profile",
            "evidence_collection",
            "scored_candidates",
            "ranked_candidates",
        }
        return next((item for item in self.tool_produces(tool_name) if item in supported), "")

    def tool_binds_primary_artifact(self, tool_name: str) -> bool:
        """判断工具主产物是否参与计划级 canonical 绑定；引用解析等中间结果可显式关闭。"""
        return bool(self._tool_entry(tool_name).get("bind_primary_artifact", True))

    def tool_scope(self, tool_name: str) -> str:
        """读取工具声明的作用域类型，避免 inspection 按具体工具名猜测 scope。"""
        return str(self._tool_entry(tool_name).get("scope") or "")

    def tool_binding_kind(self, tool_name: str) -> str:
        """查询工具 binding_kind，plan_building builder 只执行该配置。"""
        tool = self._tool_entry(tool_name)
        return str(tool.get("binding_kind") or "")

    def first_tool_with_role(self, role: str) -> str:
        """返回某 role 的首个工具，用于规则层的受控默认选择。"""
        return next(iter(self.tools_with_role(role)), "")

    def first_tool_with_binding_kind(self, binding_kind: str) -> str:
        """按 binding_kind 找默认工具，避免节点写私有工具名 fallback。"""
        return next(
            (
                str(name)
                for name, raw in dict(self.tool_policy.get("tools", {}) or {}).items()
                if str(dict(raw or {}).get("binding_kind") or "") == binding_kind
            ),
            "",
        )

    def _intent_entry(self, intent: str) -> dict[str, Any]:
        """读取 intents.yaml 中单个 intent 配置，是公开查询方法的内部复用点。"""
        intents = dict(self.intents.get("intents", {}) or {})
        return dict(intents.get(intent, {}) or {})

    def _intent_tool_entry(self, intent: str) -> dict[str, Any]:
        """读取 tool_policy intent_tools 条目，避免每个查询方法重复展开 YAML shape。"""
        policy = dict(self.tool_policy.get("intent_tools", {}) or {})
        return dict(policy.get(intent, {}) or {})

    def _scenario_tool_entry(self, entry: dict[str, Any], scenario: str = "") -> dict[str, Any]:
        """读取 scenario 级工具策略；不存在时返回空 dict 交给调用方回落 intent 默认。"""
        scenario_key = str(scenario or "").strip()
        scenarios = dict(entry.get("scenarios", {}) or {})
        if scenario_key and isinstance(scenarios.get(scenario_key), dict):
            return dict(scenarios.get(scenario_key) or {})
        return {}

    def _tool_entry(self, tool_name: str) -> dict[str, Any]:
        """读取单个工具 metadata，集中处理缺省空对象。"""
        return dict(dict(self.tool_policy.get("tools", {}) or {}).get(tool_name, {}) or {})
