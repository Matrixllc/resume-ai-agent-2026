# Condition Normalizer Flow

这份文档只讲代码阅读线。

更高层总结看 `README.md`；YAML 和 taxonomy 字段归属看 `YAML_USAGE.md`。

## 阅读顺序

```text
1. CONDITION_FLOW.md
2. condition_normalizer.py
```

## 主流程

```text
normalize_router_output
-> _merge_candidate_reference_conditions
-> normalize_conditions
-> mark_preference_targets
-> _drop_context_reference_candidate_names
-> _is_context_reference_candidate
-> _contains_context_term_only
-> _contains_known_candidate_name
```

## normalize_router_output

输入：

```text
router_output: RouterOutput
question: str
```

输出：

```text
RouterOutput
```

只更新：

```text
conditions
normalized_conditions
```

它不改：

```text
intent
scenario_decisions
context_policy
requires_jd
requires_evidence
allowed_tool_names
risk_flags
```

执行过程：

```text
1. out_of_scope 直接清空 conditions / normalized_conditions
2. 读取 router_output.conditions
3. 如果 conditions 为空，用 extract_conditions(question) fallback
4. 合并显式候选人名字
5. normalize_conditions(...) 生成 NormalizedCondition
6. mark_preference_targets(...) 标记偏好目标
7. 清理上下文指代词误抽取
8. model_copy 写回 RouterOutput
```

为什么这么做：

```text
router 只负责 raw conditions；
condition_normalizer 才负责标准化；
后续 execution_policy / compiler / validator 只应该依赖 normalized_conditions。
```

## _merge_candidate_reference_conditions

输入：

```text
conditions: list[QueryCondition]
question: str
```

输出：

```text
list[QueryCondition]
```

作用：

```text
把当前问题里显式出现的候选人名字补成 candidate_name condition。
```

为什么这么做：

```text
候选人名字不是 taxonomy 分类。
domain/skill/concept 走 shared_taxonomy；
candidate_name 来自候选人识别和数据层。
```

例子：

```text
孟连星有哪些金融项目？
```

补出：

```json
{
  "type": "candidate_name",
  "raw_value": "孟连星",
  "evidence": "孟连星"
}
```

## normalize_conditions

来源：

```text
resume_query_ai_qa.core.rules.condition_rules
```

输入：

```text
list[QueryCondition]
```

输出：

```text
list[NormalizedCondition]
```

作用：

```text
把 raw condition 标准化成 normalized condition。
```

例子：

```json
{
  "type": "domain",
  "raw_value": "金融风控"
}
```

可能变成：

```json
{
  "type": "domain",
  "raw_value": "金融风控",
  "normalized_value": "金融",
  "matched_by": "contains",
  "confidence": 0.95,
  "retrieval_terms": ["金融风控", "金融", "风控"]
}
```

为什么这么做：

```text
后续工具需要稳定的 normalized_value 和 retrieval_terms，
不能直接拿用户原话拼检索参数。
```

## mark_preference_targets

来源：

```text
resume_query_ai_qa.core.rules.condition_rules
```

输入：

```text
normalized_conditions
question
```

输出：

```text
normalized_conditions
```

作用：

```text
识别“适合做什么/推荐谁做什么/按什么岗位排序”里的目标条件。
```

例子：

```text
谁最适合做金融风控？
```

这里的：

```text
金融风控
```

更像“评价目标”，不一定是硬筛选条件。函数会把 matched_by 改成：

```text
preference_target:...
```

为什么这么做：

```text
避免把排序/推荐目标误当成必须 hard filter 的条件。
```

## _drop_context_reference_candidate_names

输入：

```text
conditions or normalized_conditions
router_output
```

输出：

```text
清理后的 conditions or normalized_conditions
```

作用：

```text
如果 context_policy 表示当前问题引用上一轮候选集合，
就删除被误抽成 candidate_name 的上下文词。
```

要清理的上下文 ref types：

```python
{"ranking_top", "ranking_top_k", "candidate_pool", "comparison_pair"}
```

例子：

```text
第一名有哪些项目？
```

这里：

```text
第一名
```

不是候选人真实姓名，而是上一轮 ranking_top 的引用。它应该由 `context_policy`
解决，不应该留在 `candidate_name` condition 里。

## _is_context_reference_candidate

作用：

```text
判断一个 candidate_name condition 是否只是上下文引用词。
```

判断逻辑：

```text
1. 收集 raw_value / normalized_value / evidence
2. 如果包含真实候选人姓名，则保留
3. 否则如果只是“第一名/这些人/这两个人”等上下文词，就删除
```

## _contains_context_term_only

作用：

```text
判断文本是不是上下文词加少量语气/连接词。
```

例子：

```text
第一名
第一名的
这些人里
```

这类不是候选人姓名。

## _contains_known_candidate_name

作用：

```text
读取 data_access 中的已知候选人姓名，判断文本里是否真的包含候选人。
```

为什么这么做：

```text
如果文本里有真实候选人名，就不能因为它同时包含上下文词而误删。
```

## 示例走读

问题：

```text
第一名有哪些金融项目？
```

router 可能输出：

```json
{
  "conditions": [
    {"type": "scope", "raw_value": "项目经验"},
    {"type": "domain", "raw_value": "金融"},
    {"type": "candidate_name", "raw_value": "第一名"}
  ],
  "context_policy": {
    "uses_context": true,
    "context_ref_type": "ranking_top",
    "evidence": ["第一名"]
  }
}
```

condition_normalizer 处理：

```text
1. 保留 scope/domain
2. normalize_conditions 生成 normalized scope/domain
3. 发现 candidate_name=第一名 只是 context reference
4. 删除 candidate_name=第一名
5. 保留 context_policy，让后续节点解析上一轮第一名
```

最终：

```json
{
  "conditions": [
    {"type": "scope", "raw_value": "项目经验"},
    {"type": "domain", "raw_value": "金融"}
  ],
  "normalized_conditions": [
    {"type": "scope", "normalized_value": "项目经验"},
    {"type": "domain", "normalized_value": "金融"}
  ]
}
```
