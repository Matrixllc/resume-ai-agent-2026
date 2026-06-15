# Scoring Package

`scoring` 是 Query-AI 的确定性 JD / 简历评分内核。

一句话：

```text
scoring = JD 标准 / 通用标准 + 候选人 brief + evidence -> CandidateScore -> 排序
```

它不直接作为 graph node 运行，也不直接被 executor 调用。executor 调用的是 `tools/scoring_tools.py` 里的工具 adapter，adapter 再调用这里的评分函数。

## 架构位置

```text
plan_compiler
-> ToolCallSpec(score_candidates_for_jd)
-> executor
-> tools/scoring_tools.py
-> scoring/jd.py
-> CandidateScore[]
-> rank_candidates
-> execution_validator / aggregator / answer_validator
```

评分标准来源有两类：

```text
configs/jd_scoring.yaml = 权重、默认 JD 标准路径、评分规则开关
scoring/JD.md           = 岗位标准库，按岗位/领域选择 section
```

## 它做什么

- 加载默认岗位标准：`load_default_jd_criteria()`。
- 在没有具体 JD 时生成通用简历排序标准：`load_general_resume_criteria()`。
- 从 JD 文本中规则抽取 `JDScoringCriteria`：`extract_jd_criteria()`。
- 基于候选人 brief、证据和 criteria 计算 `CandidateScore`。
- 对已有 `CandidateScore` 做确定性排序：`rank_candidates()`。

## 它不做什么

- 不判断用户 intent。
- 不选择工具。
- 不读取 graph state。
- 不调用 LLM。
- 不查询候选人列表。
- 不生成最终答案。
- 不替 aggregator 重排候选人。

## 输入和输出

主要输入：

```text
CandidateBrief
EvidenceRef[]
JDScoringCriteria
configs/jd_scoring.yaml
scoring/JD.md
```

主要输出：

```text
JDScoringCriteria
CandidateScore
CandidateScore[]
```

`CandidateScore` 里最关键的是：

```text
resume_identity
name
total_score
dimension_scores
strengths
risks
evidence_refs
missing_info
recommendation_reason
tie_break_reason
```

## 文件职责

| 文件 | 职责 | 阅读入口 |
| --- | --- | --- |
| `jd.py` | JD 标准加载、criteria 抽取、单人评分、排序 | `load_default_jd_criteria` -> `score_candidate_material_for_jd` -> `rank_candidates` |
| `JD.md` | 岗位标准库，不是单一岗位 JD | 看一级标题 section |
| `__init__.py` | 稳定导出评分 API | `__all__` |

## 和 Tools 的边界

`tools/scoring_tools.py` 负责：

- 按 candidate id 加载 `CandidateBrief`。
- 为候选人加载 evidence。
- 调用 `score_candidate_material_for_jd()`。
- 把结果作为工具输出交给 executor。

`scoring/jd.py` 负责：

- 只基于已经加载好的 brief / evidence / criteria 计算分数。
- 不知道本轮 QueryPlan，也不处理 `$ref` 参数绑定。

## 准确性边界

当前评分是 deterministic rule scoring，不是招聘最终结论。

它能保证：

- 同一输入得到同一分数和排序。
- 评分维度来自配置权重。
- 排序 tie-break 有稳定规则。
- strengths / risks 尽量绑定 evidence。

它不能保证：

- 真正招聘专家级判断。
- JD 文本语义完全理解。
- 所有工作年限都精确。
- 候选人证据缺失时还能可靠判断。

## 阅读顺序

1. [README.md](README.md)
2. [SCORING_FLOW.md](SCORING_FLOW.md)
3. [YAML_USAGE.md](YAML_USAGE.md)
4. [jd.py](jd.py)
5. [../tools/scoring_tools.py](../tools/scoring_tools.py)
6. [../tools/YAML_USAGE.md](../tools/YAML_USAGE.md)

## 是否需要优化架构

当前不建议拆架构。

理由：

- `scoring` 目录只有一个核心实现文件，职责窄。
- 对外 API 很少，已经通过 `__init__.py` 收口。
- 工具 adapter 已经在 `tools/scoring_tools.py`，不需要把 executor 逻辑挪进来。
- 如果现在拆 `criteria.py` / `ranking.py` / `features.py`，会增加跳转，但不会明显降低复杂度。

更合适的优化是：

- 补 README / FLOW / YAML_USAGE。
- 清理 helper docstring。
- 保留现有函数名和行为。

## 验收

```bash
rg "Scoring Package|SCORING_FLOW|YAML_USAGE|load_default_jd_criteria|score_candidate_material_for_jd|rank_candidates" resume_query_ai_qa/scoring
./.venv/bin/python -m compileall -q resume_query_ai_qa/scoring
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
