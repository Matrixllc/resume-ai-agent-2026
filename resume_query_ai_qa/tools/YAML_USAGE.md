# Tools YAML Usage

## 这份文档看什么

这份文档说明 `tools/` 和 YAML 的关系。

核心结论：

```text
tools 自己通常不直接读 tool_policy.yaml 来决定能不能被调用。
```

工具能不能用、什么时候用、怎么绑定参数，主要由上游节点和配置决定：

```text
router / planner / plan_compiler / plan_validator / execution_repair
```

工具函数只接收 executor 已绑定好的参数，然后执行只读数据访问。

## tool_policy.yaml.tools

路径：

```text
resume_query_ai_qa/configs/tool_policy.yaml
```

字段示意：

```yaml
tools:
  filter_candidates:
    produces: [candidate_collection]
    roles: [candidate_source, structured_filter]
    fallback_tool: hybrid_search_candidates
    default_output_key: candidate_pool
```

谁用：

```text
plan_compiler
plan_validator
execution_repair
core.inspection.plan_artifacts
core.config.model
```

tools/registry.py 的关系：

```text
TOOL_REGISTRY 里必须存在同名 Python function。
tool_policy.yaml.tools 里必须声明同名工具的 metadata。
```

通俗理解：

```text
registry.py = 代码里真的能调用哪些函数
tool_policy.yaml = 系统允许怎么使用这些函数
```

## tool_policy.yaml.intent_tools

字段示意：

```yaml
intent_tools:
  candidate_filter:
    preferred_tools: [...]
    allowed_tools: [...]
    scenarios:
      hard_filter:
        allowed_tools: [...]
```

谁用：

```text
router finalizer allowed_tool_names
planner tool hints
plan_compiler generic binding
plan_validator tool policy check
```

工具函数自己不读：

```text
filter_candidates 不知道自己是不是当前 intent 允许的工具。
它只执行 executor 传进来的参数。
```

## compiler_templates.yaml.tool_calls

路径：

```text
resume_query_ai_qa/configs/compiler_templates.yaml
```

作用：

```text
workflow template 中定义稳定工具链。
```

例子：

```text
filter_candidates
-> count_candidates
-> score_candidates_for_jd
-> rank_candidates
-> search_candidate_evidence
```

谁用：

```text
plan_compiler
plan_validator artifact contract
```

tools 关系：

```text
template 里出现的 tool name 必须存在于 TOOL_REGISTRY。
```

## answer_layouts.yaml / aggregator_tasks.yaml required_tools

路径：

```text
resume_query_ai_qa/configs/answer_layouts.yaml
resume_query_ai_qa/configs/aggregator_tasks.yaml
```

用途：

```text
aggregator 根据成功的 ToolResult.tool_name 匹配 task/layout。
```

例子：

```yaml
required_tools:
  all:
    - count_candidates
    - rank_candidates
```

tools 关系：

```text
这些 YAML 不调用工具。
它们只判断哪些工具结果已经存在，从而选择回答框架。
```

## validation.yaml

相关字段：

```yaml
retry_limits:
  executor_tool_call: 2

business_limits:
  ...

intent_result_requirements:
  ...
```

谁用：

```text
executor retry
execution_validator
plan/execution repair route
answer_validator privacy/answer checks
```

tools 关系：

```text
工具函数抛异常或返回 business error 后，
executor/execution_validator 根据 validation/tool_policy 判断怎么处理。
```

## 工具直接读取的外部配置

少量工具会通过 `resume_query_tools.config.get_tools_config()` 读取底层数据位置。

### structured_store_file

使用位置：

```text
candidate_tools._structured_tags_by_candidate
```

用途：

```text
ResumeSqlReader 读取候选人结构化标签。
```

### chroma_dir / chroma_collection

使用位置：

```text
common.vector_search_rows
```

用途：

```text
ResumeVectorReader 检索 Chroma project chunks。
```

注意：

```text
这些是底层数据访问配置，不是 Query-AI 的 tool policy。
```

## Registry 对齐检查

工具新增或改名时，需要同时检查：

```text
tools/registry.py TOOL_REGISTRY
configs/tool_policy.yaml tools.*
configs/tool_policy.yaml intent_tools.*
configs/compiler_templates.yaml tool_calls
configs/answer_layouts.yaml required_tools
configs/aggregator_tasks.yaml required_tools
benchmarks
```

## 快速区分

| 配置 | 谁真正使用 | tools 的关系 |
| --- | --- | --- |
| `tool_policy.yaml.tools` | compiler/validator/repair/artifact binding | 工具名和 metadata 必须和 registry 对齐。 |
| `tool_policy.yaml.intent_tools` | router/planner/compiler/validator | 决定哪些 intent/scenario 可用哪些工具。 |
| `compiler_templates.yaml.tool_calls` | plan_compiler | 生成 ToolCallSpec，最终 executor 调用 tools。 |
| `answer_layouts.yaml.required_tools` | aggregator | 根据 ToolResult.tool_name 匹配 layout。 |
| `aggregator_tasks.yaml.required_tools` | aggregator | 根据 ToolResult.tool_name 匹配 task type。 |
| `validation.yaml.retry_limits.executor_tool_call` | executor | 决定工具 runtime exception 重试次数。 |
| `validation.yaml.business_limits` | execution_validator | 判断 business error 是否允许保留。 |
| `resume_query_tools config` | tools/common/candidate_tools | 读取 SQL/Chroma 数据位置。 |

## 当前边界

```text
工具函数不应该自己读 intent_tools 做权限判断。
工具函数不应该根据 YAML 决定 route。
工具函数不应该写 graph state 或 trace。
工具函数可以读取底层数据源配置。
```

## 验收命令

```bash
rg "Tools Package|TOOLS_FLOW|YAML_USAGE|get_tool_registry|filter_candidates|search_candidate_evidence|resolve_candidate_reference" resume_query_ai_qa/tools
./.venv/bin/python -m compileall -q resume_query_ai_qa/tools
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_architecture_contract_benchmark.py
```
