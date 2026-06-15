# Scoring YAML Usage

`scoring` 直接使用的配置很少，核心是：

```text
configs/jd_scoring.yaml
scoring/JD.md
```

其他 YAML 主要由 router / planner / compiler / validator 决定“什么时候需要评分工具”，不是 `scoring` 自己决定。

## 1. jd_scoring.yaml

路径：

```text
resume_query_ai_qa/configs/jd_scoring.yaml
```

加载位置：

```text
core/config/loader.py
-> ResumeQAConfig.jd_scoring
-> scoring/jd.py
```

### version

```yaml
version: "v1"
```

配置版本标记。当前评分代码不按 version 分支，只作为配置合同记录。

### total_score

```yaml
total_score: 100
```

总分口径说明。当前代码按各 dimension weight 求和，不强制归一化到这个字段。

### default_jd_path

```yaml
default_jd_path: "resume_query_ai_qa/scoring/JD.md"
```

`load_default_jd_criteria()` 用它定位岗位标准库。

### dimensions

```yaml
dimensions:
  project_jd_evidence:
    weight: 40
  domain_match:
    weight: 20
  required_skill_match:
    weight: 15
  work_experience_years:
    weight: 15
  communication_or_language:
    weight: 5
  risk_penalty:
    weight: -10
```

用途：

- `extract_jd_criteria()` 把这些 weight 写入 `JDScoringCriteria.scoring_weights`。
- `load_general_resume_criteria()` 也使用同一套 weight。
- `score_candidate_material_for_jd()` 根据这些 key 计算 `dimension_scores`。

`description` 和 `evidence_required` 当前主要是配置说明/合同信息，评分函数不按它们单独分支。

### rules

```yaml
rules:
  ranking_requires_criteria: true
  no_user_jd_loads_default_jd: true
  aggregator_may_explain_but_not_reorder: true
```

这些更像跨节点合同说明：

- `ranking_requires_criteria`：plan_validator / plan semantics 会要求排序前有 criteria 工具。
- `no_user_jd_loads_default_jd`：plan_compiler 选择 criteria source 时使用这种策略。
- `aggregator_may_explain_but_not_reorder`：answer 侧必须尊重 rank 工具顺序。

`scoring/jd.py` 不直接读取 `rules` 做分支。

## 2. JD.md

路径：

```text
resume_query_ai_qa/scoring/JD.md
```

用途：

```text
load_default_jd_criteria
-> select_jd_standard_section
-> extract_jd_criteria
```

它是岗位标准库，不是单一岗位 JD。

当前按一级标题切 section，例如：

```text
金融岗位标准
运营岗位标准
能源岗位标准
后端开发岗位标准
AI/AI Search 岗位标准
通用简历标准
```

选择逻辑：

```text
target_role / job_text
-> section alias 命中
-> 返回对应 section
-> 否则返回通用简历标准
```

## 3. 其他 YAML 怎么间接影响评分

### intents.yaml

影响：

```text
requires_jd_criteria
semantic_needs
scenario_defaults
```

作用位置：

```text
router / planner / plan_compiler
```

它决定“这个问题是否需要 JD criteria / scoring”，不是评分函数自己判断。

### tool_policy.yaml

影响：

```text
load_default_jd_criteria
load_general_resume_criteria
extract_jd_criteria
score_candidates_for_jd
rank_candidates
```

作用位置：

```text
planner / plan_compiler / plan_validator / tools registry
```

它决定工具是否允许、工具角色是什么、能不能进入 QueryPlan。

### compiler_templates.yaml

影响：

```text
criteria -> score -> rank
```

作用位置：

```text
plan_compiler
```

它决定 ToolCallSpec 如何串起来，例如：

```text
load_default_jd_criteria(output_key="criteria")
score_candidates_for_jd(criteria="$criteria", output_key="scores")
rank_candidates(scored_candidates="$scores")
```

### answer_layouts.yaml / aggregator_tasks.yaml

影响：

```text
ranking answer layout
required tools
claim contract
```

作用位置：

```text
aggregator / answer_validator
```

它们决定答案怎么表达评分结果，但不改变评分分数。

## 4. 快速区分

| 配置 | 谁直接读 | 对 scoring 的影响 |
| --- | --- | --- |
| `jd_scoring.yaml.dimensions` | `scoring/jd.py` | 分数维度和权重 |
| `jd_scoring.yaml.default_jd_path` | `scoring/jd.py` | 默认岗位标准库路径 |
| `jd_scoring.yaml.rules` | compiler / validator / answer 侧为主 | 跨节点合同说明 |
| `scoring/JD.md` | `scoring/jd.py` | 默认岗位标准内容 |
| `tool_policy.yaml` | planner/compiler/validator/registry | 决定评分工具能否被调用 |
| `compiler_templates.yaml` | plan_compiler | 决定 criteria/score/rank 调用顺序 |

## 5. 边界提醒

`scoring` 可以读配置权重和 JD 标准，但不负责决定本轮是否要评分。

如果问题是：

- “为什么用了排序工具？”看 router / execution_policy / plan_compiler。
- “为什么 criteria 是默认 JD？”看 plan_compiler 的 criteria source 选择。
- “为什么这个人分数高？”看 `score_candidate_material_for_jd()` 和 `CandidateScore.dimension_scores`。
- “为什么答案顺序这样？”看 `rank_candidates()` 和 aggregator 是否保留顺序。
