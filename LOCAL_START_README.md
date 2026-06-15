# 本地启动指南

这份说明面向第一次下载项目的新使用者。按顺序做完后，可以在本地启动后端、前端，并导入简历数据进行问答。

## 1. 环境要求

- Python 3.12 推荐。
- Node.js 使用前端目录里的 `.nvmrc`，当前为 Node 20。
- 默认使用 OpenAI；如果要用 Ollama，需要另外配置本地模型。

## 2. 配置环境变量

在项目根目录复制模板：

```bash
cp .env.example .env
```

本地最少需要修改这些值：

```env
OPENAI_API_KEY=你的_OpenAI_Key
RESUME_APP_PASSWORD=本地访问密码
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
RESUME_API_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

本地启动可以不设置 `RESUME_DATA_ROOT`。默认运行数据会写到仓库根目录的 `data/`。

如果部署到服务器或 PaaS，必须设置持久化目录：

```env
RESUME_DATA_ROOT=/persistent/resume-query
```

## 3. 安装并启动后端

在项目根目录执行：

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn resume_query_api.main:app --host 127.0.0.1 --port 8000
```

后端启动后，另开一个终端验证：

```bash
curl http://127.0.0.1:8000/health
```

看到 `status: ok`，并且 SQL / Chroma 为 `ok`，说明后端可用。

## 4. 安装并启动前端

另开一个终端：

```bash
cd resume_query_frontend_v3
./scripts/use-node.sh
npm install
npm run dev:local
```

浏览器访问：

```text
http://127.0.0.1:3000
```

进入页面后，输入 `.env` 里的 `RESUME_APP_PASSWORD`。

## 5. 准备简历数据

新下载的项目不会自带已构建好的 SQLite / Chroma 数据。需要先导入简历。

方式一：把简历文件放到统一数据目录：

```text
data/resume/
```

支持常见的 `.pdf`、`.docx`、`.doc` 文件。

然后在前端点击批量重建/扫描入库。

方式二：直接在前端上传简历文件。上传后会自动写入候选人库。

## 6. 本地验证问题

入库完成后，可以在前端尝试：

```text
有哪些候选人？
运营的候选人有谁？
某个候选人有哪些项目？
```

如果候选人为空，通常是还没有导入简历，或 `data/` 里的 Chroma / SQLite 被清空后没有重新入库。

## 7. 常见问题

### 前端 build 报 Node 版本太低

需要使用 Node 20：

```bash
cd resume_query_frontend_v3
./scripts/use-node.sh
```

再执行：

```bash
npm run build
```

### 访问接口提示访问密码无效

确认 `.env` 里的：

```env
RESUME_APP_PASSWORD=本地访问密码
```

前端登录时输入同一个密码。

### Chroma 或 SQLite 为空

本地启动只会启动服务，不会自动生成候选人库。需要先上传简历或把简历放到 `data/resume/` 后执行批量重建。

### 部署到服务器后数据丢失

生产环境必须配置持久化数据目录：

```env
RESUME_DATA_ROOT=/persistent/resume-query
```

否则 `data/` 下的 SQLite、Chroma、上传简历和扫描目录可能会随服务重启丢失。
