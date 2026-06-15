# Tools Package

## 一句话

`resume_query_ai_qa/tools/` 是 Query-AI 的只读工具层。

```text
plan_compiler -> QueryPlan/ToolCallSpec
plan_validator -> registry/signature/tool_policy check
executor -> get_tool_registry -> tool functions
execution_validator / aggregator / answer_validator -> consume ToolResult
```

工具函数只负责读取事实材料并返回结构化结果。它们不规划、不选工具、不解释 intent、不生成最终答案。

## 架构位置

```text
router / planner / compiler
-> QueryPlan / ToolCallSpec
-> plan_validator
-> executor
-> tools
-> ToolResult[]
-> execution_validator
-> aggregator
```

`tools` 是 executor 真正调用的函数集合。上游决定“用哪个工具、传什么参数”，工具自己只执行已给定的只读操作。

## 固定边界

Tools 做：

```text
读取候选人列表、画像、项目证据、标签、结构化库、向量库
按已给参数筛选、计数、召回、评分、比较材料组装
返回 CandidateBrief / EvidenceRef / dict / score 等结构化结果
```

Tools 不做：

```text
不判断 intent
不选择工具
不生成 QueryPlan
不读取 graph state
不决定 route
不修复 plan
不生成最终自然语言答案
不越过 executor 直接写 ToolResult
```

## 文件职责

| 文件 | 职责 | 不做什么 |
| --- | --- | --- |
| `registry.py` | 稳定工具注册表，给 executor / validator 获取工具名到函数的映射。 | 不实现工具逻辑，不解释 tool_policy。 |
| `candidate_tools.py` | 候选人列表、结构化筛选、计数、单人 brief。 | 不排序、不推荐、不生成答案。 |
| `profile_tools.py` | 单人/多人画像素材，默认隐藏联系方式。 | 不判断适配性，不泄露默认隐藏 contact。 |
| `evidence_tools.py` | 项目证据检索、候选人开放召回。 | 不做 JD 排序，不直接下推荐结论。 |
| `scoring_tools.py` | JD 评分工具 adapter，把候选人事实交给 scoring 模块。 | 不定义评分规则。 |
| `comparison_tools.py` | 双人比较事实包。 | 不选赢家，不输出比较结论。 |
| `reference_tools.py` | 姓名、代词、候选池、排名引用解析。 | 不查画像，不排序，不回答问题。 |
| `common.py` | 跨工具共享的数据转换、文本匹配、向量检索 helper。 | 不承载工具权限或 intent policy。 |
| `__init__.py` | 稳定公开导出入口。 | 不增加额外行为。 |

## registry.py

职责：

```text
TOOL_REGISTRY: tool_name -> Python function
get_tool_registry(): 返回 registry 副本
```

谁用：

```text
executor
plan_validator
plan_repair LLM prompt
plan_compiler generic binding
```

注意：

```text
TOOL_REGISTRY 的工具名必须和 tool_policy.yaml.tools.* 保持一致。
registry 是代码真入口，tool_policy.yaml 是配置合同。
```

## candidate_tools.py

职责：

```text
list_all_candidates
filter_candidates
count_candidates
get_candidate_brief
```

主要输入：

```text
domains_any / domains_all
skills_all / concepts_all
candidate_ids
keywords / education_keywords / job_intent
```

主要输出：

```text
CandidateBrief[]
int
CandidateBrief
```

数据来源：

```text
resume_query_tools.list_candidates
resume_query_tools.get_candidate_profile
resume_query_tools.get_project_evidence
structured_store_file tags
```

注意：

```text
filter_candidates 是 hard filter，不负责语义召回。
count_candidates 只数传入候选池；不传 candidates 时才数全量。
```

## profile_tools.py

职责：

```text
get_candidate_profile_intro
get_candidate_profiles_intro
```

主要输出：

```text
画像素材 dict
profiles dict
```

数据来源：

```text
SQLite profile
work / education / project manifest
get_candidate_evidence
```

注意：

```text
include_contact 默认 False。
批量画像最多展示 MAX_PROFILE_DISPLAY_COUNT 位。
超限返回 business error，不抛异常中断整条链。
```

## evidence_tools.py

职责：

```text
get_candidate_evidence
search_candidate_evidence
hybrid_search_candidates
```

主要输出：

```text
EvidenceRef[]
dict[candidate_id, EvidenceRef[]]
open recall result dict
```

数据来源：

```text
Chroma project chunks
SQLite project manifest
candidate profile / tags / work / project metadata
```

注意：

```text
project evidence 是强证据。
hybrid_search_candidates 是开放召回，不等于 JD 排序。
```

## scoring_tools.py

职责：

```text
score_candidate_for_jd
score_candidates_for_jd
```

主要输入：

```text
candidate_id(s)
JDScoringCriteria
config
```

主要输出：

```text
CandidateScore
CandidateScore[]
```

数据来源：

```text
candidate brief
candidate evidence
resume_query_ai_qa.scoring
```

注意：

```text
空 candidate_ids 是真实空结果，不会自动变成全量候选人。
```

## comparison_tools.py

职责：

```text
build_comparison_pack
```

主要输入：

```text
candidate_ids exactly 2
domain / query
```

主要输出：

```text
briefs
profiles
evidence
```

注意：

```text
只构造比较事实包，不直接判断谁更强。
candidate_ids 不等于 2 时抛 ValueError，交给 executor/validator 处理。
```

## reference_tools.py

职责：

```text
resolve_candidate_reference
```

主要输入：

```text
text
session_context
```

主要输出：

```text
resolved
needs_clarification
candidate_ids
source
match_candidates
```

数据来源：

```text
list_all_candidates
session_context.last_* fields
candidate mention extraction
fuzzy matching
```

注意：

```text
它只解析“第一名/这些人/刚才那个人/某个姓名”指向哪些 candidate ids。
它不查画像、不排序、不回答。
```

## common.py

职责：

```text
CandidateBrief / EvidenceRef 构造 helper
候选人检索文本拼接
taxonomy/domain normalize
向量检索 reader helper
文本命中和评分 helper
```

注意：

```text
common.py 是工具共享 helper，不是 policy 层。
不要把 intent/tool 权限判断写到这里。
```

## YAML 关系

Tools 自己通常不直接读 `tool_policy.yaml` 来决定能不能用。

```text
tool_policy.yaml -> compiler/validator/repair 决定能否生成和执行工具
TOOL_REGISTRY    -> executor 真正找到 Python function
tool function    -> 执行只读数据访问
```

少量外部配置由工具直接读取：

```text
resume_query_tools.config.get_tools_config()
structured_store_file
chroma_dir
chroma_collection
```

详细配置地图见 `YAML_USAGE.md`。

## 阅读顺序

```text
1. README.md
2. TOOLS_FLOW.md
3. YAML_USAGE.md
4. registry.py
5. candidate_tools.py
6. profile_tools.py
7. evidence_tools.py
8. scoring_tools.py
9. comparison_tools.py
10. reference_tools.py
11. common.py
```

## 是否需要拆分

不需要。

原因：

```text
tools 已经按领域拆分。
registry 只是 facade。
common.py 虽然 helper 多，但都是跨工具共享的数据转换、文本匹配、向量检索 helper。
现在强行拆 common 会影响多个工具导入，收益不大。
```

## 验收

```bash
rg "Tools Package|TOOLS_FLOW|YAML_USAGE|get_tool_registry|filter_candidates|search_candidate_evidence|resolve_candidate_reference" resume_query_ai_qa/tools
./.venv/bin/python -m compileall -q resume_query_ai_qa/tools
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_architecture_contract_benchmark.py
```
