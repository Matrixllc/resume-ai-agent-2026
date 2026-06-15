# resume_query_frontend_v3

`resume_query_frontend_v3` 是展示层。它只调用 `resume_query_api`，负责候选人浏览、
问答输入、答案展示和 Debug 面板。

前端不补事实、不重排候选人、不绕过 API 直接读数据。

## 页面职责

| 页面/区域 | 负责 | 边界 |
|---|---|---|
| 候选人信息 | 展示 API 返回的候选人、教育、工作经历、项目和源文件预览。 | 不解析简历，不合并项目事实。 |
| AI 问答 | 提交自然语言问题，展示答案、证据、排序、比较结果。 | 不改数量、名单、排名或证据。 |
| 问答状态 | 展示默认 `trace.diagnosis.headline`。 | 不自行推断失败原因。 |
| Debug 面板 | 展示完整 trace、route events、compiler、tools、validator errors。 | 不调用后端 detail 文件。 |
| 入库按钮 | 触发 demo ingestion。 | 不把入库包装成生产管理能力。 |

## Query-AI Debug 怎么看

默认回答即会显示最小诊断。需要详细排查时勾选 Debug 并重新提问。

推荐顺序：

1. `问答状态`：看 `diagnosis.headline`。
2. `Trace ID`：复制后可在后端 `data/logs/query_ai/` 查完整 JSON。
3. `Route Events`：看 validator 路由到 execute、repair、fail、clarify 还是 fallback。
4. `链路追踪`：看 node 顺序、`status` 和 `summary`。
5. `Compiler Hint Selection`：看 tool hint accepted/rejected 和原因。
6. `Tools`：看工具是否成功、是否有 warnings/errors。
7. `validation_errors`：看错误发生在 plan、execution 还是 answer。

典型判断：

- `可能的金融领域候选人`：应是 ok，开放召回可能走 generic/hybrid。
- `金融领域候选人有哪些？`：应保持 hard filter，不能用 query-only hybrid 伪造硬筛。
- `孙可欣 有能源相关的经历么`：证据为空也应 ok，并显示 `empty_evidence` warning。
- `他有哪些金融经历？` 且无上下文：当前是 `failed + context_missing_not_recoverable`。
- `今天天气怎么样？`：应是 out_of_scope，tools 为空。

## 启动

在项目根目录启动后端：

```bash
./.venv/bin/uvicorn resume_query_api.main:app --host 127.0.0.1 --port 8000
```

启动前端：

```bash
cd resume_query_frontend_v3
./scripts/use-node.sh
npm install
npm run dev:local
```

访问：

```text
http://127.0.0.1:3000
```

## 构建检查

项目 Node 版本写在 `.nvmrc`，当前为 Node 20.12.1。上线前必须使用：

```bash
./scripts/use-node.sh
npm run build
```

`npm run lint` 当前会触发 Next.js 首次 ESLint 配置交互。补非交互 ESLint 配置前，
上线阻塞项以 `npm run build` 为准。

## 展示边界

- QA 答案来自 `/qa/ask`。
- 候选人详情来自 `/candidates/*`。
- 排序和比较顺序来自后端工具结果。
- 原始证据来自 `used_evidence_refs`。
- 前端只能展示 `diagnosis`，不能自己判断业务失败原因。
