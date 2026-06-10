# 问题总结

## 目的

这个文档用于沉淀后续架构方案中需要展开的问题，尤其是 Query-AI 问答链路里的 router、intent 推断、条件抽取、候选人匹配、上下文引用、YAML 配置联动和性能边界。

后续每次继续讨论架构相关问题时，可以把问题、简短结论、相关代码和可展开方向追加到这里，方便最后整理成系统架构说明或答辩材料。

## 已总结问题

### 1. Router 如何通过关键词、条件抽取、上下文引用和 guard 推断 intent

**问题：**
router 是怎么判断用户 intent 的？关键词、条件抽取、上下文引用和 guard 分别起什么作用？

**结论：**
router 先对问题做预处理，再生成 LLM 或 rule draft，随后通过 guard 收敛边界，最后用 finalizer 统一重算 intent、sub intents、scenario、requires_jd、requires_evidence 和 allowed tools。关键词和 signals 用来判断用户想做什么，conditions 用来表达领域/技能/候选人等筛选条件，context_policy 用来表示是否引用上一轮结果，guard 用来覆盖不稳定或越界的判断。

**相关代码：**
- `resume_query_ai_qa/nodes/router/node.py::route_question`
- `resume_query_ai_qa/nodes/router/rules.py::build_rule_router_draft`
- `resume_query_ai_qa/nodes/router/guard.py::apply_router_guards`
- `resume_query_ai_qa/nodes/router/finalizer.py::finalize_router_output`

**后续可展开：**
可以画出 router 的 6 段流程图，并解释哪些字段是 draft 产生的，哪些字段由 finalizer 作为权威结果重算。

### 2. Signals 做什么用

**问题：**
signals 是什么？为什么不直接从关键词推 intent？

**结论：**
signals 是 router 的中间信号层，用来把用户问题拆成一组可组合的布尔信号和上下文策略，例如是否是双人比较、是否有候选人引用、是否引用上一轮候选池、是否要求证据、是否是排序或面试问题。后续 intent handlers 根据 signals 组合出 candidate_count、candidate_list、candidate_profile_intro、evidence_question、candidate_ranking、candidate_compare_pair 或 compound。

**相关代码：**
- `resume_query_ai_qa/nodes/router/signals.py::detect_signals`
- `resume_query_ai_qa/nodes/router/rule_types.py::RouterSignals`
- `resume_query_ai_qa/nodes/router/rules.py::infer_sub_intents`

**后续可展开：**
可以用示例说明同一句话如何先变成 signals，再由不同 handler 合并成单 intent 或 compound intent。

### 3. 正则、taxonomy YAML 和 condition extraction 的关系

**问题：**
是不是先用正则提取一段话，再用 taxonomy YAML 提取里面的关键字？

**结论：**
更准确地说是并行抽取。候选人指代、专业、scope 等结构会用正则或模板抽取；领域、技能、概念则通过遍历 shared_taxonomy YAML 中的 aliases，在整句文本里做 exact、contains 或 fuzzy 匹配，生成 QueryCondition，再由 condition_normalizer 转成 NormalizedCondition。taxonomy 主要负责把“金融、风控、推荐系统、Python”等词标准化成可被工具消费的结构化条件。

**相关代码：**
- `resume_query_ai_qa/core/rules/condition_rules.py::extract_conditions`
- `resume_query_ai_qa/core/rules/condition_rules.py::normalize_conditions`
- `resume_query_ai_qa/core/rules/taxonomy.py::taxonomy_entries`
- `resume_query_ai_qa/core/rules/taxonomy.py::match_taxonomy`
- `resume_query_ai_qa/configs/condition_rules.yaml`
- `shared_taxonomy/domains/*.yaml`

**后续可展开：**
可以区分“文本模式抽取”和“taxonomy 标准化匹配”，并说明为什么 domain/skill/concept 不适合散落硬编码在 router 里。

### 4. 候选人姓名如何识别和解析

**问题：**
对于人名，是不是把一段话放进去，然后用专门的 list_all_candidates() 去匹配？

**结论：**
人名不走 taxonomy YAML，而是走候选人名单匹配。router 阶段先用正则模板和已知姓名列表判断问题是否“像是在引用候选人”；真正绑定候选人 ID 时，plan 会调用 resolve_candidate_reference。这个工具会读取 list_all_candidates()，逐个候选人生成 alias，并与用户输入做 direct match、fuzzy match 和上下文匹配，最后返回 resolved、needs_clarification 和 candidate_ids。

**相关代码：**
- `resume_query_ai_qa/core/rules/candidate_mentions.py::extract_candidate_mentions`
- `resume_query_ai_qa/nodes/router/signals.py::candidate_mentions`
- `resume_query_ai_qa/tools/reference_tools.py::resolve_candidate_reference`
- `resume_query_ai_qa/tools/reference_tools.py::_candidate_aliases`
- `resume_query_ai_qa/tools/candidate_tools.py::list_all_candidates`

**后续可展开：**
可以专门画一条“候选人引用解析链路”：router 粗识别 -> compiler 生成 resolve_candidate_reference -> executor 注入 session_context -> tool 输出候选人 ID 或澄清状态。

### 5. `_known_candidate_names()` 和 `list_all_candidates()` 有什么区别

**问题：**
`_known_candidate_names()` 是不是公共函数？它和 `list_all_candidates()` 有什么区别？

**结论：**
`_known_candidate_names()` 是 router signals 中的轻量增强函数，内部调用 core.data_access 的 `list_known_candidate_names()`，只返回姓名字符串列表，用来判断用户问题里是否出现了已知候选人姓名。`list_all_candidates()` 是正式工具层函数，返回 CandidateBrief 对象列表，包含姓名、resume_identity、领域、技能等信息，用于 resolve_candidate_reference、筛选、计数、排序和证据链路。

**相关代码：**
- `resume_query_ai_qa/nodes/router/signals.py::_known_candidate_names`
- `resume_query_ai_qa/core/data_access/candidate_index.py::list_known_candidate_names`
- `resume_query_ai_qa/tools/candidate_tools.py::list_all_candidates`

**后续可展开：**
可以说明 core.data_access 和 tools 层的边界：router 只拿轻量索引增强判断，正式事实读取和候选人绑定由工具层完成。

### 6. 是否每个问题都会重新跑链路

**问题：**
现在运行链路是什么？是不是每个问题都会重新生成一次？

**结论：**
每个用户问题都会重新跑一遍 QA graph：router -> condition_normalizer -> execution_policy -> planner/plan_compiler -> validator -> executor -> aggregator -> answer_validator -> final。但不是每个问题都会调用 resolve_candidate_reference，只有画像、证据、比较、面试问题等需要绑定候选人的 intent 才会生成这个工具调用。当前候选人 alias 匹配没有全局预计算索引；一旦调用 resolve_candidate_reference，会重新 list_all_candidates() 并遍历匹配。

**相关代码：**
- `resume_query_ai_qa/graph/build.py::build_state_graph`
- `resume_query_ai_qa/graph/nodes.py::router_node`
- `resume_query_ai_qa/nodes/executor/node.py::execute_plan_with_context`
- `resume_query_ai_qa/tools/reference_tools.py::resolve_candidate_reference`

**后续可展开：**
可以把“每轮都会重新判断 intent”和“只有需要候选人绑定才调用 resolve tool”分开讲，避免误解为所有工具每轮都全量执行。

### 7. 几百或几千候选人时，人名匹配性能如何

**问题：**
如果候选人有几百个、几千个，现在逐个匹配还能不能用？如何优化？

**结论：**
当前实现是内存里的 for 循环匹配：list_all_candidates() 后逐个候选人生成 alias，再判断 alias 是否出现在用户问题里。几百到几千候选人通常还能接受，但主要开销在每次重新读取候选人、重新生成 alias、重新遍历全部候选人。如果规模或并发上来，建议做候选人 alias 缓存索引，在启动或数据摄取后预计算 alias -> candidate 映射，后续问题直接查缓存；更大规模可考虑 Trie、Aho-Corasick、SQLite FTS 或搜索引擎。

**相关代码：**
- `resume_query_ai_qa/tools/reference_tools.py::resolve_candidate_reference`
- `resume_query_ai_qa/tools/reference_tools.py::_candidate_aliases`
- `resume_query_ai_qa/tools/reference_tools.py::_fuzzy_candidate_matches`
- `resume_query_ai_qa/tools/candidate_tools.py::list_all_candidates`

**后续可展开：**
可以作为架构优化点：先保留确定性匹配语义，再引入 alias_index 缓存和数据摄取后的刷新机制，避免改变现有业务判断。

### 8. Router、scenario 和工具计划的边界

**问题：**
router 是不是直接决定调用哪个工具？scenario 和 tool plan 是怎么衔接的？

**结论：**
router 不直接生成工具调用。router 输出 intent、sub_intents、conditions、context_policy 和 scenario_decisions；execution_policy 根据 scenario 决定走 workflow_template 还是 generic_tool_binding；plan_compiler 再根据 compiler_templates.yaml、tool_policy.yaml、binding_kind 和 normalized_conditions 生成 ToolCallSpec。这样 router 只判断“用户要什么”和“执行语义”，工具选择和参数绑定交给 compiler。

**相关代码：**
- `resume_query_ai_qa/core/rules/execution_policy_rules.py::resolve_execution_decision`
- `resume_query_ai_qa/nodes/execution_policy/execution_policy.py::resolve_execution_policy`
- `resume_query_ai_qa/nodes/plan_compiler/templates.py::compile_with_workflow_templates`
- `resume_query_ai_qa/core/rules/plan_building/builders.py::generic_call_for_tool`
- `resume_query_ai_qa/configs/scenarios.yaml`
- `resume_query_ai_qa/configs/compiler_templates.yaml`
- `resume_query_ai_qa/configs/tool_policy.yaml`

**后续可展开：**
可以在架构方案中强调分层：router 做语义入口协议，condition_normalizer 做条件权威收口，execution_policy 做调度，compiler 做工具计划。

### 9. 版本快照是否需要自己维护

**问题：**
数据库已有 MySQL、Oracle、PostgreSQL、SQLite 的事务隔离或 MVCC，业务层为什么还要维护 version snapshot？

**结论：**
数据库事务或 MVCC 只能保证单个数据库内部不会读到半提交数据。如果查询只读 SQL 表，这一层已经能提供基本读写隔离。但当前系统不只依赖 SQLite，还涉及 Chroma 向量库、内存 alias index、tag inverted index、候选人姓名快照以及可能的多进程查询服务。数据库无法自动保证这些组件同时属于同一批已发布数据。

因此业务层仍建议维护 `published_data_version` 或 `index_version`，作为跨组件一致性的发布标记。上传侧完成 SQLite 写入、Chroma 写入、索引构建和校验后，再原子发布新版本；查询侧在一次请求开始时绑定某个稳定快照，本次请求从头到尾只消费这个快照。这样可以避免读到“SQL 已更新但内存索引未刷新”或“候选人表已更新但向量库未完成”的中间状态。

**相关代码：**
- `resume_query_api/routes/ingestion.py::ingest_resumes`
- `resume_query_v3/core/data_layer/storage/structured_store.py::upsert`
- `resume_query_ai_qa/tools/reference_tools.py::resolve_candidate_reference`
- `resume_query_ai_qa/tools/candidate_tools.py::filter_candidates`

**后续可展开：**
可以把这块总结为：底层依赖数据库事务/MVCC 保证单存储一致性；上层维护 `published_data_version` 保证 SQL、向量库和内存索引之间的跨组件一致性。

## 后续待补充问题

- LLM router 和 rule router 的职责边界、失败回退和 risk_flags 如何设计。
- condition_normalizer 为什么要独立于 router，而不是在 router 里直接生成 normalized_conditions。
- plan_validator 和 execution_validator 分别防什么问题。
- session_context 如何写回 last_candidate、last_candidate_pool、last_ranking 和 comparison_pair。
- tool_policy.yaml 如何约束工具白名单、preferred tools、binding_kind 和 artifact 产物。
- aggregator 如何保证答案只基于 grounded context，不私自补事实。
- `index_meta / published_data_version` 表结构如何设计，以及单机内存快照如何演进到多进程共享失效通知。
