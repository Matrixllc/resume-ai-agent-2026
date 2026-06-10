"""Canonical artifact bindings for compiled plans."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import ArtifactBinding, QueryPlan, RouterOutput, ToolCallSpec

from resume_query_ai_qa.core.rules.plan_building.source_policy import candidate_required_scope, plan_calls


def with_artifact_bindings(
    plan: QueryPlan,
    router_output: RouterOutput | None,
    *,
    rejected_producers: list[dict[str, Any]] | None = None,
    config: ResumeQAConfig | None = None,
) -> QueryPlan:
    """根据工具 metadata 为计划刷新产物绑定，不执行工具也不改变调用顺序。"""
    return plan.model_copy(
        update={
            "artifact_bindings": artifact_bindings_from_plan(
                plan,
                router_output,
                rejected_producers=rejected_producers,
                config=config,
            )
        }
    )


def artifact_bindings_from_plan(
    plan: QueryPlan,
    router_output: RouterOutput | None,
    *,
    rejected_producers: list[dict[str, Any]] | None = None,
    config: ResumeQAConfig | None = None,
) -> list[ArtifactBinding]:
    """读取 ``tool_policy.yaml.produces``，为计划生成可追踪的主产物与消费关系。"""
    cfg = config or load_config()
    calls = plan_calls(plan)
    required_scope = candidate_required_scope(router_output)
    consumers_by_root: dict[str, list[str]] = {}
    for call in calls:
        for root in candidate_id_refs_from_call(call):
            consumers_by_root.setdefault(root, []).append(call.name)
    bindings: list[ArtifactBinding] = []
    canonical_source: str = ""
    for call in calls:
        artifact_type = artifact_type_for_binding(call, cfg)
        if not artifact_type:
            continue
        artifact_id = call.output_key or cfg.default_output_key(call.name)
        source_artifact_id = source_artifact_id_for_call(call)
        refs = candidate_id_refs_from_call(call)
        if artifact_type == "candidate_collection":
            if canonical_source:
                continue
            canonical_source = artifact_id
        accepted_scope = dict(call.arguments) if cfg.tool_scope(call.name) == "filtered" else {}
        bindings.append(
            ArtifactBinding(
                artifact_id=artifact_id,
                artifact_type=artifact_type,  # type: ignore[arg-type]
                required_scope=required_scope if artifact_type in {"candidate_collection", "candidate_count", "evidence_collection"} else ranking_required_scope(router_output),
                accepted_producer=call.name,
                accepted_scope=accepted_scope,
                rejected_producers=list(rejected_producers or []) if artifact_type == "candidate_collection" else [],
                consumers=list(dict.fromkeys(consumers_by_root.get(artifact_id, []))),
                source_artifact_id=source_artifact_id,
                candidate_id_refs=refs,
            )
        )
        if artifact_type != "evidence_collection" and "evidence_collection" in cfg.tool_produces(call.name):
            bindings.append(
                ArtifactBinding(
                    artifact_id=f"{artifact_id}_evidence",
                    artifact_type="evidence_collection",
                    required_scope=required_scope,
                    accepted_producer=call.name,
                    accepted_scope=accepted_scope,
                    rejected_producers=[],
                    consumers=list(dict.fromkeys(consumers_by_root.get(artifact_id, []))),
                    source_artifact_id=source_artifact_id,
                    candidate_id_refs=refs,
                )
            )
    return bindings


def artifact_type_for_binding(call: ToolCallSpec, config: ResumeQAConfig) -> str:
    """返回计划账本需要登记的产物类型。"""
    if call.name == "resolve_candidate_reference":
        return "candidate_collection"
    return config.tool_primary_artifact_type(call.name)


def ranking_required_scope(router_output: RouterOutput | None) -> dict[str, Any]:
    """获取排序必需范围并返回。"""
    if router_output is None:
        return {}
    scope = candidate_required_scope(router_output)
    if router_output.context_policy.uses_context:
        scope = {"context_ref_type": router_output.context_policy.context_ref_type, **scope}
    return scope


def source_artifact_id_for_call(call: ToolCallSpec) -> str:
    """根据调用生成来源产物标识并返回。"""
    refs = argument_ref_roots(call.arguments)
    for dependency in call.depends_on:
        if dependency in refs and dependency not in {"criteria"}:
            return dependency
    return next((root for root in refs if root not in {"criteria"}), "")


def candidate_id_refs_from_call(call: ToolCallSpec) -> list[str]:
    """从调用提取候选人标识引用集合并返回。"""
    refs: list[str] = []
    for root in argument_ref_roots(call.arguments):
        if root not in refs and root not in {"criteria", "scores"}:
            refs.append(root)
    if "candidate_ids" in call.arguments and isinstance(call.arguments["candidate_ids"], list):
        refs.append("candidate_ids")
    return refs


def argument_ref_roots(value: Any) -> list[str]:
    """获取参数引用roots并返回。"""
    roots: list[str] = []
    if isinstance(value, dict):
        if "$ref" in value:
            return [str(value["$ref"])]
        for item in value.values():
            roots.extend(argument_ref_roots(item))
    elif isinstance(value, list):
        for item in value:
            roots.extend(argument_ref_roots(item))
    elif isinstance(value, str) and value.startswith("$"):
        roots.append(value[1:].split(".", 1)[0])
    return list(dict.fromkeys(roots))
