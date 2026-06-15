# Scoring Flow

这份文档按代码阅读顺序解释 `scoring` 怎么把 JD 标准、候选人事实和证据变成排序分数。

## 1. 总链路

```text
plan_compiler
-> score_candidates_for_jd ToolCallSpec
-> executor
-> tools/scoring_tools.score_candidates_for_jd
-> scoring.score_candidate_material_for_jd
-> scoring.rank_candidates
-> ToolResult
```

`scoring` 自己不处理 ToolCallSpec，也不解析 `$ref`。这些已经在 plan_compiler / executor / tools adapter 完成。

## 2. Criteria 来源

### 默认岗位标准

入口：

```text
load_default_jd_criteria(target_role, job_text, config)
```

过程：

```text
configs/jd_scoring.yaml.default_jd_path
-> scoring/JD.md
-> select_jd_standard_section
-> extract_jd_criteria
-> JDScoringCriteria
```

作用：

- 用户问“谁最适合金融风控”这类需要 JD/岗位口径的问题时使用。
- `target_role` / `job_text` 用来选择 `JD.md` 中更贴近的 section。
- 没匹配到时回退到“通用简历标准”。

### 通用简历标准

入口：

```text
load_general_resume_criteria(config)
```

过程：

```text
configs/jd_scoring.yaml.dimensions
-> JDScoringCriteria(source="manual", target_role="通用简历优先级")
```

作用：

- 没有明确 JD，又需要排序时使用。
- 排的是“简历事实完整度、证据覆盖、技能/领域标签、风险缺口”，不是岗位绝对匹配。

### 用户 JD 文本

入口：

```text
extract_jd_criteria(jd_text)
```

过程：

```text
JD text
-> known domain aliases
-> known skill terms
-> experience_signals
-> jd_scoring.yaml.dimensions
-> JDScoringCriteria
```

当前是规则抽取，不调用 LLM。

## 3. 单人评分

入口：

```text
score_candidate_material_for_jd(brief, evidence_refs, criteria, config)
```

输入：

```text
CandidateBrief
EvidenceRef[]
JDScoringCriteria
```

过程：

```text
_criteria
-> _is_general_resume_criteria
-> _score_candidate_for_general_resume  # 通用标准
```

或：

```text
_candidate_text
-> _dimension_overlap_score       # domain / required skill
-> _project_evidence_score        # evidence 是否命中 JD 词
-> _work_experience_years_score   # 保守估算工作年限
-> _communication_score
-> _risk_penalty
-> CandidateScore
```

输出：

```text
CandidateScore(
  total_score,
  dimension_scores,
  strengths,
  risks,
  evidence_refs,
  missing_info,
  recommendation_reason
)
```

## 4. 通用评分分支

如果 criteria 是通用简历标准：

```text
_score_candidate_for_general_resume
```

主要看：

```text
证据条数
领域标签数量
技能标签数量
工作经历数量
项目记录数量
缺失风险
```

它不会声称“最适合某岗位”，只能表达“当前简历事实下优先级更高”。

## 5. 排序

入口：

```text
rank_candidates(scored_candidates)
```

过程：

```text
CandidateScore[]
-> _ranking_key
-> stable sorted list
-> _tie_break_reason  # 第一/第二名总分相同时补充原因
```

排序 key 顺序：

```text
total_score desc
project_jd_evidence desc
domain_match desc
required_skill_match desc
work_experience_years desc
risk_penalty desc
evidence_refs count desc
strengths count desc
name asc
resume_identity asc
```

注意：aggregator 必须保留 `rank_candidates` 的顺序，不能为了文案重排。

## 6. 示例：金融候选人有几个，谁最强，依据是什么？

上游计划通常会生成：

```text
filter_candidates(domains_any=["金融"])
-> count_candidates(candidate_ids=$candidate_pool.resume_identity[])
-> load_default_jd_criteria(target_role="金融")
-> score_candidates_for_jd(candidate_ids=$candidate_pool.resume_identity[], criteria=$criteria)
-> rank_candidates(scored_candidates=$scores)
-> search_candidate_evidence(...)
```

进入 `scoring` 的时候，前面的事情已经完成：

```text
candidate_ids 已经解析
CandidateBrief 已经由 tools adapter 加载
EvidenceRef 已经由 tools adapter 加载
criteria 已经是 JDScoringCriteria
```

`scoring` 只负责：

```text
brief + evidence + criteria
-> CandidateScore
-> ranking order
```

## 7. 常见疑问

### 为什么不用 LLM 打分？

当前目标是稳定可复现。LLM 可以后续用于抽取 JD，但最终评分和排序仍应保持确定性，否则同一输入可能给出不同顺序。

### 为什么没有直接查数据库？

数据库和证据加载属于 tools adapter 的职责。`scoring` 只消费已加载事实，避免评分层既查数据又打分，边界会乱。

### JD.md 是用户 JD 吗？

不是。`JD.md` 是岗位标准库。用户如果提供 JD 文本，走 `extract_jd_criteria()`；没有用户 JD 时，`load_default_jd_criteria()` 从标准库选一个 section。

### 分数是不是招聘结论？

不是。分数是排序工具的中间结果，最终答案必须保留证据、风险和缺失信息。
