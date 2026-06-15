# Tools Flow

## 阅读目标

这份文档讲工具从“计划中的 ToolCallSpec”到“executor 返回 ToolResult”的流转。

Tools 本身不决定要不要调用。调用链是：

```text
plan_compiler 生成 ToolCallSpec
-> plan_validator 检查 registry / signature / tool_policy
-> executor.get_tool_registry
-> execute_tool_call
-> tool function
-> ToolResult
-> execution_validator
-> aggregator
```

## 1. 工具调用主链

### 1.1 `plan_compiler`

做什么：

```text
生成 ToolCallSpec:
  name
  arguments
  depends_on
  output_key
```

例子：

```text
ToolCallSpec(
  name="filter_candidates",
  arguments={"domains_any": ["金融"]},
  output_key="candidate_pool"
)
```

### 1.2 `plan_validator`

检查：

```text
tool name 是否在 get_tool_registry()
tool name 是否被 tool_policy 允许
arguments 是否符合 Python function signature
depends_on / $ref 是否合法
artifact contract 是否满足
```

注意：

```text
validator 只检查，不执行工具。
```

### 1.3 `executor`

执行顺序：

```text
get_tool_registry()
-> 按 QueryPlan 顺序遍历 ToolCallSpec
-> bind_argument_refs
-> execute_tool_call
-> tool function(**arguments)
-> ToolResult
```

注意：

```text
工具抛异常不会直接生成答案失败。
executor 会包装成 failed ToolResult，后续 execution_validator 再决定 fail/repair/clarify。
```

### 1.4 `ToolResult`

后续消费者：

```text
execution_validator = 检查结果是否满足计划
aggregator = 基于结果生成答案
answer_validator = 检查 answer claims/evidence 是否来自结果
state.session_context = final 后写下一轮上下文
```

## 2. Candidate Source Flow

相关工具：

```text
list_all_candidates
filter_candidates
count_candidates
get_candidate_brief
```

典型链路：

```text
filter_candidates
-> count_candidates
-> rank_candidates / search_candidate_evidence / get_candidate_profiles_intro
```

### `list_all_candidates`

用途：

```text
返回所有候选人的轻量 CandidateBrief。
```

常见场景：

```text
候选人列表
全量 count
候选人引用解析
```

### `filter_candidates`

用途：

```text
按 domains/skills/concepts/candidate_ids/keywords 等结构化条件筛候选人。
```

输入通常来自：

```text
condition_normalizer.normalized_conditions
plan_compiler filter_args binding
session_context candidate pool
```

输出：

```text
CandidateBrief[]
```

注意：

```text
filter_candidates 是确定性 hard filter。
开放召回走 hybrid_search_candidates。
```

### `count_candidates`

用途：

```text
统计候选池数量。
```

注意：

```text
如果传入 candidates，就只统计这个候选池。
如果不传，才统计全量候选人。
```

## 3. Evidence Flow

相关工具：

```text
get_candidate_evidence
search_candidate_evidence
hybrid_search_candidates
```

### `get_candidate_evidence`

用途：

```text
返回单个候选人的 EvidenceRef[]。
```

数据来源：

```text
Chroma project chunks
SQLite project manifest fallback
```

### `search_candidate_evidence`

用途：

```text
对一个或多个 candidate_id 检索证据。
```

典型输入：

```text
query
candidate_ids
limit_per_candidate
max_candidates
```

输出：

```text
dict[candidate_id, EvidenceRef[]]
```

### `hybrid_search_candidates`

用途：

```text
开放候选人召回。
```

数据通道：

```text
SQL profile
tags
work experience
project metadata
vector evidence
```

注意：

```text
hybrid_search_candidates 只回答“谁相关”，不是“谁最适合”。
排序/推荐仍应走 scoring/ranking。
```

## 4. Ranking / Scoring Flow

相关工具：

```text
load_default_jd_criteria
load_general_resume_criteria
extract_jd_criteria
score_candidate_for_jd
score_candidates_for_jd
rank_candidates
```

其中 criteria / rank 的实现来自：

```text
resume_query_ai_qa.scoring
```

tools 中的 `scoring_tools.py` 做 adapter：

```text
候选人 brief + evidence
-> score_candidate_material_for_jd
-> CandidateScore
```

典型链路：

```text
filter_candidates
-> load_default_jd_criteria
-> score_candidates_for_jd
-> rank_candidates
```

注意：

```text
score_candidates_for_jd(candidate_ids=[])
返回空列表，不能自动扩成全量候选人。
```

## 5. Comparison Flow

相关工具：

```text
build_comparison_pack
```

输入：

```text
candidate_ids exactly 2
domain / query
```

输出：

```text
candidate_ids
briefs
profiles
evidence
```

注意：

```text
工具只准备事实包。
最终“谁更适合”的表达由 aggregator 根据事实生成。
```

## 6. Reference Resolution Flow

相关工具：

```text
resolve_candidate_reference
```

输入：

```text
text
session_context
```

可解析：

```text
明确姓名
候选人 ID
这些人 / 这批人
第一名 / 刚才第一位
他 / 她 / 这个人
这两个人
模糊姓名
```

输出：

```text
resolved
needs_clarification
candidate_ids
source
match_candidates
```

注意：

```text
resolve_candidate_reference 不查画像、不排序、不生成答案。
```

## 7. Profile Flow

相关工具：

```text
get_candidate_profile_intro
get_candidate_profiles_intro
```

输出内容：

```text
basic profile
education_experiences
work_experiences
skills/domains
projects
evidence_refs
contact_hidden
```

注意：

```text
include_contact 默认 False。
get_candidate_profiles_intro 超过展示上限会返回 business error payload。
```

## 8. 示例完整走读

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

可能的工具链：

```text
filter_candidates
-> count_candidates
-> load_default_jd_criteria
-> score_candidates_for_jd
-> rank_candidates
-> search_candidate_evidence
```

流转：

```text
1. plan_compiler 把 “金融” 变成 filter_args:
   {"domains_any": ["金融"]}

2. executor 调用 filter_candidates:
   返回金融候选人 CandidateBrief[]

3. count_candidates 接收 candidate_pool:
   返回候选人数

4. load_default_jd_criteria:
   返回默认 JD 评分标准

5. score_candidates_for_jd:
   根据候选人事实和证据打分

6. rank_candidates:
   对 CandidateScore[] 排名

7. search_candidate_evidence:
   为候选池检索支持排序/推荐的项目证据

8. execution_validator:
   检查 count/ranking/evidence 是否满足合同

9. aggregator:
   基于 ToolResult[] 生成答案
```

## 9. 排查入口

```text
工具名找不到          -> registry.py / tool_policy.yaml.tools
参数不匹配            -> plan_validator signature check / tool function signature
筛选结果不对          -> candidate_tools.filter_candidates
开放召回结果不对      -> evidence_tools.hybrid_search_candidates
证据为空              -> evidence_tools.get_candidate_evidence / search_candidate_evidence
排序分数不对          -> scoring_tools.py / resume_query_ai_qa.scoring
双人比较失败          -> comparison_tools.build_comparison_pack
“第一名/这些人”解析错 -> reference_tools.resolve_candidate_reference / session_context
联系方式泄露          -> profile_tools include_contact / answer_validator privacy
```

## 10. 验收命令

```bash
rg "Tools Package|TOOLS_FLOW|YAML_USAGE|get_tool_registry|filter_candidates|search_candidate_evidence|resolve_candidate_reference" resume_query_ai_qa/tools
./.venv/bin/python -m compileall -q resume_query_ai_qa/tools
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_architecture_contract_benchmark.py
```
