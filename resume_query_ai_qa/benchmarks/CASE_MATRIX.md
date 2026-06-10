# Case Matrix

权威 case matrix：`benchmark_cases.yaml`。

当前分类覆盖：

- hard filter、open recall、count/list
- profile、evidence、compare、ranking、compound
- follow-up 有上下文与缺上下文
- 单候选人 fit analysis
- interview generation、out-of-scope
- Operations、Finance、Energy 参数化领域回归

新增问题时优先补业务期望：`family`、问题、session fixture、intent/scenario/status/context、安全约束。不要在 case 中填写工具链、artifact、route 或固定答案文案。
