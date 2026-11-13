# Insight Agent v2

一个**本地原型**的自然语言数据分析 Agent：上传 CSV 或用示例数据，直接提问，由后端完成意图识别、元数据召回、SQL / 工具调用与确定性计算，前端展示结论、图表和完整执行证据。

设计原则：**所有数字都由 pandas / SQLite 等确定性工具产生，模型只负责选工具、组织语言**，不参与算数。

> 当前状态：本地原型，不含部署、鉴权与多租户；未做线上发布。

## 分支结构与协作方式

本仓库采用「一个集成基线 + 两个独立工程分支」：

| 分支 | 内容 | 定位 |
| --- | --- | --- |
| `main` | `backend/` + `frontend/` 全量 | 默认分支、集成基线，按本文档一次启动即可跑通全链路 |
| `backend` | 仅 `backend/` | 后端独立工程视图，README 面向后端开发 / 测试 / 运行 |
| `frontend` | 仅 `frontend/` | 前端独立工程视图，README 面向前端开发 / 构建 / 预览 |

两侧遵循前后端分离的工程约定：

- 各自独立依赖（`requirements.txt` / `pyproject.toml` 与 `package.json`）、独立启动与构建，不共享源码
- 唯一协作边界是 HTTP 契约：前端 `src/api/client.js` 的 `BASE = '/api/v1'`，开发期由 `vite.config.js` 把 `/api` 代理到 `127.0.0.1:8000`；后端 CORS 白名单见 `conf/app_config.yaml`
- 契约以运行后端的 `/docs`（OpenAPI）与 `app/schemas/agent.py` 为准；`/runs` 与 `/graph/runs/stream` 返回 `text/event-stream`
- 接口变更顺序：**先改后端契约，再同步前端调用方**

> 说明：行业里分支通常按版本 / 功能划分（main / develop / feature），按技术层拆分会让「一次跑通全链路」变困难。因此这里保留 `main` 全量基线，两个拆分分支作为可分别交付与部署的独立工程视图；日常开发仍建议在 `main` 或功能分支上进行。三个分支的 `.gitignore` 都保留跨侧通用忽略规则，避免切换分支时残留的 `.env` / `node_modules` / `*.db` 被误提交。

## 能力概览

- 数据接入：CSV 上传（≤ 10 MB）、一键生成带已知异常尖峰的示例数据、数据集列表 / 删除
- 工作台：5 张概览统计卡、40 行数据预览、对话式结果卡、智能报告导出、快捷提问
- 两套推理链路：ReAct 自研循环（`/runs`）与 LangGraph 状态图（`/graph/runs*`），可在界面切换
- 检索与执行：元数据三路召回 + RRF、SQL 生成 → 白名单校验 → 纠错 → 只读执行 → pandas 交叉校验
- 可解释性：逐节点 SSE 时间线、召回证据、SQL 检查器、ReAct 推理轨迹

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Vue 3 + Vite 5，端口 `5173` |
| 后端 | Python + FastAPI，端口 `8000` |
| 编排 | LangGraph `StateGraph`；LangChain `ChatOpenAI` / `ChatPromptTemplate` / tools |
| 存储 | 单文件 SQLite（业务表 + 元数据表 + 向量表 + FTS5 取值索引） |
| 模型 | DashScope 兼容端点 `qwen3.8-max`；默认 mock 规划器，不联网 |
| 其他 | 自研护栏、SSE 事件流、Skill 包、MCP client、RAG 索引（本地哈希 embedding） |

## 目录结构

以下为 `main` 分支的全量结构；`backend` / `frontend` 分支各只保留对应目录与专属 README、`.gitignore`。

```text
data-analysis-agent/
├── backend/
│   ├── app/
│   │   ├── agent/          # LangGraph 状态、节点、图、逐节点事件流
│   │   ├── api/v1/         # health / datasets / agent / graph 路由
│   │   ├── clients/        # LLM、embedding、SQLite 客户端
│   │   ├── conf/           # 单一配置源（YAML + dataclass + Secrets）
│   │   ├── core/agent/     # 自研 ReAct 循环、规划器、护栏、记忆
│   │   ├── infra/          # 数据仓储、向量库、SQLite 连接
│   │   ├── models/         # 元数据表结构
│   │   ├── prompt/         # 模板加载器
│   │   ├── rag/            # 索引、检索、引用、embedder
│   │   ├── repositories/   # 元数据仓储
│   │   ├── schemas/        # Pydantic 请求契约
│   │   ├── services/       # 元数据构建、召回、SQL、注册表、统计、交叉校验
│   │   ├── skills/  mcp/  tools/   # 技能包、MCP client、确定性工具
│   │   └── main.py         # FastAPI 入口（lifespan 建知识库 + 编译图）
│   ├── conf/               # app_config.yaml、meta_knowledge.yaml（非敏感参数）
│   ├── prompts/            # 外置提示词模板
│   ├── tests/              # 四套无需联网的回归脚本
│   ├── requirements.txt    # pip 依赖
│   ├── pyproject.toml      # uv 工程声明
│   └── .env.example        # 环境变量样例（仅占位符）
└── frontend/
    ├── src/                # App.vue、api/client.js、components/*
    ├── vite.config.js      # /api 代理到 127.0.0.1:8000
    └── package.json
```

## 快速开始

### 环境要求

- Python 3.12+（开发验证环境 3.14.6；`backend/pyproject.toml` 声明 `requires-python >=3.14`，用 `uv sync` 时会按该声明约束）
- Node.js 18+
- 无需外部数据库、无需云服务；默认 mock 模式不联网、不消耗模型额度

### 1. 启动后端

```bash
cd backend
python -m venv .venv
# Windows PowerShell：.venv\Scripts\Activate.ps1
# macOS / Linux / Git Bash：source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # PowerShell 用：Copy-Item .env.example .env
python -m uvicorn app.main:app --app-dir . --port 8000 --reload
```

也可以从仓库根启动：`python -m uvicorn app.main:app --app-dir backend --port 8000 --reload`。
配置路径由 `Path(__file__).parents[2]` 定位到 `backend/`，不依赖启动时的工作目录。

首次启动会在 lifespan 中自动完成两件事：按 `conf/meta_knowledge.yaml` 重建元数据知识库，以及编译 LangGraph 状态图。健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

交互式 API 文档：http://127.0.0.1:8000/docs

> 网络受限、无法 `pip install` 时，可复用本机已有虚拟环境：把它的 `site-packages` 加入 `PYTHONPATH`，再用系统 Python 启动。这是离线开发的替代方案，不是项目依赖。

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`，因此两个端口必须同时运行（开发期真前后端分离 + CORS）。

### 3. 第一次提问

在界面顶栏打开导入弹窗，选择「生成示例数据」，或调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/datasets/demo \
  -H "Content-Type: application/json" -d '{"rows":48}'
```

拿到返回的 `id` 后，在输入框直接问，例如「统计线上渠道的销售总额」「帮我做异常识别」。右侧「执行证据」可查看节点时间线、召回证据和 SQL 闭环结果。

纯命令行验证逐节点 SSE（Git Bash / macOS）：

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/graph/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"统计线上渠道的销售总额","dataset_id":"<上一步的 id>"}'
```

## 环境变量

优先级：**环境变量 > `backend/.env` > `backend/conf/app_config.yaml`**。`.env` 已被 `.gitignore` 排除，密钥仅在内存中持有，不写日志、不入库。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_MODE` | `mock` | `mock` = 内置确定性规划器；`real` = 调用真模型。缺密钥时自动降级为 mock |
| `ALIQWEN_API_KEY` | 空 | real 模式必需；兼容旧名 `aliQwen-api` |
| `ALIQWEN_BASE_URL` | DashScope 兼容端点 | OpenAI 兼容 base_url |
| `ALIQWEN_MODEL` | `qwen3.8-max` | 模型名 |
| `AGENT_ENGINE` | `react` | 仅影响旧 `/runs`；`/graph/runs*` 始终走 LangGraph |
| `APP_DATA_DIR` | `./data` | 数据目录，默认 `backend/data`（已忽略） |
| `APP_DB_PATH` | 自动 | 覆盖 SQLite 路径，回归测试用它指向临时库 |
| `AGENT_MAX_STEPS` 等 | 见 YAML | 护栏参数，如 `AGENT_MAX_ROWS=500` |

## 主要接口

统一前缀 `/api/v1`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health`、`/health/llm` | 健康检查 / 模型连通性自检（不回显凭据） |
| POST | `/datasets` | 上传 CSV（`multipart` 字段 `file`，≤ 10 MB，自动尝试 utf-8-sig / gbk / utf-8） |
| GET | `/datasets` | 数据集列表 |
| POST | `/datasets/demo` | 生成示例数据，`rows` 范围 6–240 |
| POST | `/datasets/{id}/register` | 幂等重注册物理表并同步元数据 |
| GET | `/datasets/{id}/schema` | SQL 执行靶：表名、列、类型、样例取值 |
| GET | `/datasets/{id}/stats` | 行数 / 字段类型 / 缺失 / 完整度 / 重复行 / 规模 |
| GET | `/datasets/{id}/preview?limit=40` | 数据预览，默认 40 行，上限 200 |
| DELETE | `/datasets/{id}` | 删除数据集 |
| POST | `/runs` | ReAct SSE 事件流，请求体 `{question, dataset_id}` |
| POST | `/graph/runs` | LangGraph 同步运行，一次返回完整节点轨迹 |
| POST | `/graph/runs/stream` | LangGraph 逐节点 SSE：`meta → node×N → final → done` |

`/graph/runs*` 请求体：`{question, dataset_id?, force_branch?}`，`force_branch` 可选 `""` / `sql` / `react`，留空按意图自动路由。

## 回归测试与构建

测试全部使用临时 SQLite、固定 mock 模式，不联网、不碰项目主库：

```bash
cd backend
python tests/test_tools.py          # 确定性工具
python tests/test_agent_smoke.py    # ReAct 链路
python tests/test_architecture.py   # 分层 / 配置 / 密钥字面量
python tests/test_p1.py             # 注册表 / SQL 靶 / SSE / HTTP 契约

cd ../frontend
npm run build
```

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 前端请求失败 / CORS 报错 | 后端未启动，或访问地址不是 `http://localhost:5173` / `http://127.0.0.1:5173`（白名单在 `backend/conf/app_config.yaml` 的 `server.cors_origins`） |
| 改了后端端口 | 同步修改 `frontend/vite.config.js` 的 proxy target |
| 上传被拒 | 仅支持 CSV，≤ 10 MB，且需能被 utf-8-sig / gbk / utf-8 解析 |
| 结论标注「确定性工具」 | mock 模式下的正常行为；要模型增强请设 `LLM_MODE=real` 并配置密钥 |
| 界面统计卡为 0 或空 | 先生成示例数据或上传 CSV；统计来自 `GET /datasets/{id}/stats` 的后端逐行计算 |

## 当前边界

- SQL 生成仍以确定性 mock 模板为主，真模型 function calling 与 `prompts/sql_correct.md` 纠错尚未接入
- 尚无问答金标准评测集；复杂查询的交叉校验会明确标注「未覆盖」，不谎称已校验
- 两套引擎端点并存：`AGENT_ENGINE` 只影响 `/runs`，前端默认走 LangGraph
- Skill / MCP / RAG 都是本地实现，不依赖任何外部服务；向量检索使用本地哈希 embedding + SQLite
- `.env`、`backend/data/`、`*.db`、`node_modules/`、`frontend/dist/` 均已被忽略，请勿把密钥写进仓库
