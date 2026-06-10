# Interview QA

这份文档用专家视角回答 `ai-query` 的常见架构问题。重点不是介绍功能，而是解释取舍、字段意义、边界和上下游关系。

## 1. 为什么不用自由 Agent？

招聘问答有事实一致性和合规要求。自由 Agent 容易绕过工具、扩大 scope、编造证据。这里用 graph pipeline，把每一步变成可验证 contract：理解、规划、编译、执行、表达分层，出错也能定位。

代价是牺牲一点灵活性；收益是可解释、可验证、可部署、可运营。

## 2. 为什么 router 不直接选工具？

router 只负责意图识别。如果让 router 选工具，它会同时承担分类和执行规划，边界会混。后续新增工具时也会污染 router。工具选择应该在 compiler，根据 intent、scenario、tool policy 和 workflow 统一处理。

框架上看，这是 parse 和 compile 的职责分离。

## 3. 为什么需要 `ExecutionDecision`？

它把“走哪条执行路径”显式化。没有它，template/generic 的判断会散在 planner/compiler 里，后续很难解释为什么跳过 planner、为什么走 generic。

字段意义：

- `compiler`：选择 `workflow_template` 或 `generic_tool_binding`。
- `planner`：generic 路径上用 rule 还是 LLM planner。
- `workflow_name`：命中的稳定 workflow。
- `scenarios`：每个 intent 的执行约束。
- `reason`：给 trace 和排查看的解释。

## 4. 为什么 template 命中要跳过 planner？

稳定高频问题不需要每次重新规划。比如“介绍某人”工具顺序固定，直接 template 更快、更稳定、更便宜。

planner 留给开放、新增、复杂场景。这个取舍类似框架里的 fast path / slow path。

## 5. 为什么 generic 还需要 compiler？

planner 产的是语义计划，不是安全可执行计划。compiler 负责把语义步骤绑定到合法工具、参数、artifact、source contract。

这样 LLM 即使给了 tool hint，也不能直接越权执行。

## 6. 为什么 scenario 不是 intent？

intent 表示“用户要什么”，scenario 表示“应该怎么受约束地执行”。

同一个 intent 在不同上下文里可能不同执行方式。比如 `candidate_filter`：

- `hard_filter`：结构化 SQL/filter。
- `open_recall`：语义召回。

这让业务语义和执行策略解耦。

## 7. 为什么 count/list 必须共用 source？

否则可能出现“数量来自金融筛选，名单来自全库”的错配。

`ArtifactBinding` 的价值就在这里：绑定同一个 `candidate_collection`，让下游 count、list、rank、evidence 消费同源数据。

## 8. 为什么 validator 分三层？

三层防的问题不同：

- `plan_validator` 防错误计划，比如错工具、缺上下文、scope 冲突。
- `execution_validator` 防工具结果不足，比如缺 count、缺 evidence、tool failed。
- `answer_validator` 防最终表达编造，比如人数、人名、排序、证据对不上。

合在一起会让错误定位变差，也不利于 repair 回到正确节点。

## 9. 为什么 aggregator 不能自己补事实？

因为 aggregator 是表达层，不是事实层。它只能基于 tool_results 写答案。

如果它补事实，answer validator 就很难保证答案可信，系统会重新变成不可控 LLM。

## 10. 为什么 bad case 也要走 graph？

统一走 graph 可以统一记录 trace、统一处理 clarification、统一输出状态。如果提前散落返回，前后端 debug 和日志审计会断裂。

## 11. 为什么 out_of_scope 不查工具？

这是效率和安全边界。非简历问题不应该消耗检索和数据库资源，也不应该泄露候选人信息。

router 直接拦截，后续 tools 为空。

## 12. 为什么要记录 `fallback_reason`？

fallback 不只是容错，也是一种生产可观测信号。它能区分“业务逻辑失败”和“LLM provider 抖动”。

比如 full-chain 里业务结果 ok，但 router LLM fallback 仍然会被严格 benchmark 报出来。

## 13. 为什么前端要有 Debug 面板？

部署后问题通常不是“答案错了”这么简单，而是要知道错在哪层。前端 Debug 能让产品/运营看到 intent、compiler、tools、errors，后端再用 trace_id 找完整日志。

这降低了研发排查成本，也让运营能判断是否是问法、数据、工具还是模型问题。

## 14. 新增场景时怎么判断改 template 还是 generic？

高频、稳定、工具顺序固定，改 template。开放、探索、还没稳定，先走 generic。等 generic case 跑稳定了，再沉淀成 template。

## 15. 这个设计最大的取舍是什么？

牺牲一点自由 Agent 的灵活性，换来可解释、可验证、可部署、可运营。

对招聘简历这种事实密集场景，这个取舍是值得的。

## 16. `SemanticPlan` 和 `QueryPlan` 有什么区别？

`SemanticPlan` 是“想做什么”：有哪些 intent steps、需要什么信息、有什么 tool hints。

`QueryPlan` 是“怎么执行”：具体 tool calls、参数、依赖、artifact binding。

这个分层让 LLM 可以参与语义规划，但不能直接进入执行层。

## 17. 为什么需要 `ToolCallSpec.depends_on`？

工具调用有依赖关系。比如先 `filter_candidates` 产生 `candidate_pool`，再 `count_candidates` 消费它。

`depends_on` 让 executor 可以按计划绑定引用，也让 trace 能解释数据从哪里来。

## 18. 为什么需要 `qa_runs.jsonl` 和 detail JSON 两套日志？

`qa_runs.jsonl` 是索引，适合快速看最近问题和 trace_id。

detail JSON 是完整排查材料，包含 node steps、artifact、debug refs、aggregator IO tail。

一个轻，一个重，符合生产排查习惯。
