# Core Package

`core` 只放跨节点共享的稳定契约、纯规则和只读 inspection helper。它不调用
graph node，不执行工具，不生成最终答案。

## Structure

| Path | Responsibility |
| --- | --- |
| `schemas.py` | Pydantic contracts shared across graph, nodes, tools, and benchmarks. |
| `config/` | YAML/env loading, typed config model, compiler flags, and config query helpers. |
| `config_validation/` | Startup-time YAML and shared taxonomy structure checks, grouped by rule source. |
| `rules/` | Deterministic business rules shared by nodes. |
| `rules/plan_building/` | QueryPlan construction rules: tool binding, argument refs, source policy, and sub-task orchestration. |
| `inspection/` | Read-only helpers for inspecting plans and tool results. |
| `answer_generation/renderers/` | Deterministic answer renderers grouped by layout/task. |
| `answer_generation/orchestration.py` | Deterministic answer input preparation, layout/context grounding, and trace meta helpers. |
| `answer_generation/llm_flow.py` | Controlled LLM fill/rewrite flow with drift and layout rejection. |
| `llm/` | QA-owned LLM client and prompt contracts. |
| `llm/client/` | Provider setup, structured invocation, Ollama JSON fallback, and LLM payload normalization. |
| `data_access/` | Low-level read-only data access for rule helpers only. |

## Boundaries

- `core` may depend on `core.schemas` and `core.config`.
- `core.rules` and `core.inspection` must stay deterministic.
- `core.llm` may call the configured LLM provider, but must not call tools or graph nodes.
- `core.data_access` may read indexed source data for narrow rule signals.
- `core` must not import `nodes`, `graph`, or `tools`.

## Rule Sources

- `configs/scenarios.yaml` 是 scenario catalog、规则 fallback 决策和 generic planner 类型的运行时真源。
- `configs/tool_policy.yaml` 是工具角色、binding kind、intent/scenario 白名单的运行时真源。
- `tool_policy.yaml.produces` 的首个可绑定产物用于生成 `ArtifactBinding`；inspection 不维护工具名到产物类型的私有映射。
- `configs/compiler_templates.yaml` 是稳定 workflow 和声明式 tool call 顺序的运行时真源。
- Python 规则模块只执行配置、提取确定性信号和实现通用算法，不维护另一份 intent/tool/scenario 对照表。

算法不变量继续保留在 Python：引用解析、canonical candidate source、结果结构读取、
证据覆盖、评分计算以及 validator/repair 控制流。这些逻辑不能仅靠 YAML 描述正确执行。

## Config Package

`core/config/` keeps loading, querying, and env switches separate. `loader.py`
reads QA runtime YAML and validates structure; `model.py` exposes stable query
methods for nodes and rules; `compiler_flags.py` owns env-driven compiler mode
checks; `tool_hints.py` normalizes hint shapes. Callers still import from
`resume_query_ai_qa.core.config`.

- Nodes should call `ResumeQAConfig` query methods instead of reading YAML.
- Compiler flags are validated once in config, not reinterpreted in compiler or
  repair nodes.
- New config query helpers belong in `model.py`; new loading behavior belongs in
  `loader.py`.

## Plan Building Rules

`core/rules/plan_building/` is the shared plan construction layer used by
compiler and repair nodes. YAML/config decides the strategy; Python builders
only execute deterministic binding rules into a `QueryPlan`.

- Tool choice, roles, `binding_kind`, default output keys, and fallback tools
  come from `tool_policy.yaml`.
- Conditions and query arguments come from `condition_rules.py` and
  `shared_taxonomy` through the taxonomy API.
- New `binding_kind` support should be added as a small builder inside
  `rules/plan_building/`, not inside a graph node.

## Answer Renderers

`core/answer_generation/renderers/` contains deterministic text renderers used
by the aggregator, rewrite, and hard fallback paths. Layout selection still
comes from `answer_layouts.yaml`; renderer modules only format already-grounded
tool facts for a selected layout/task.

- New answer styles should start in `answer_layouts.yaml`.
- Add a renderer module only when a layout needs new deterministic formatting.
- Renderer helpers must not add facts, choose tools, or bypass answer validation.

`answer_generation/generation.py` is now a compatibility facade. Deterministic
preparation and grounding live in `orchestration.py`; LLM fill/rewrite decisions
live in `llm_flow.py`. The invariant is unchanged: tool-grounded rule output is
the authority, and LLM output must pass fact drift and layout checks.

## LLM Client

`core/llm/client/` keeps the QA LLM layer modular while preserving the public
`core.llm` API. LLM output is only a structured draft; it must still pass
Pydantic validation and downstream compiler/validator/answer checks.

- Add provider setup in `client/models.py`.
- Add local-model transport fallbacks in `client/ollama_json.py`.
- Add JSON shape cleanup in `client/payload_normalization.py`; do not put
  business routing, tool choice, or answer facts there.

## Config Validation

`core/config_validation/` is the startup guard for YAML and shared taxonomy
shape. `orchestrator.py` only wires checks together; each YAML family owns its
own validator module, so config problems are fixed at the rule source instead
of patched inside nodes.

- `scenarios.py` validates intent/scenario/router-rule references.
- `tool_policy.py` validates tool allowlists, metadata, fallback, and result
  requirements.
- `compiler_templates.py` validates workflow templates and argument bindings.
- `answer_rules.py` validates answer layouts and aggregator task references.
- `condition_validation.py` validates condition and validation action rules.
- `taxonomy_validation.py` validates `shared_taxonomy` file structure.

## 中文注释规范

`core` 的函数和类需要用中文 docstring 或紧邻中文注释说明边界：负责什么、
不负责什么、被哪类调用方复用。注释重点放在规则来源、跨模块契约、非显然
fallback 和兼容入口上；简单赋值和直观循环不重复解释，避免把代码读成噪音。
