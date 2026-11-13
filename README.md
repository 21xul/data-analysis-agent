# Insight Agent v2 · 后端服务（`backend` 分支）

前后端分离后的**后端独立工程视图**：本分支只包含 `backend/`，不含任何前端源码。

| 分支 | 定位 |
| --- | --- |
| `main` | 全量集成基线，前后端都在，一次启动即可跑通全链路 |
| `backend` | 本分支：后端独立开发、测试与运行 |
| `frontend` | 前端独立开发、构建与预览 |

后端负责自然语言意图识别、元数据知识库、三路召回、SQL 生成与只读执行、确定性计算与结论组织。**所有数字由 pandas / SQLite 等确定性工具产生，模型只负责选工具、组织语言**。

## 与前端的协作契约

两侧不共享源码、依赖与构建流程，只通过下面这份 HTTP 契约协作：

| 项 | 约定 |
| --- | --- |
| API 前缀 | `/api/v1`（前端 `src/api/client.js` 中的 `BASE`） |
| 监听地址 | `http://127.0.0.1:8000` |
| 跨域白名单 | `http://localhost:5173`、`http://127.0.0.1:5173`，见 `conf/app_config.yaml` 的 `server.cors_origins` |
| 契约文档 | 启动后访问 `/docs`（Swagger UI）与 `/openapi.json`，由 Pydantic 请求模型自动生成 |
| 流式接口 | `POST /runs`、`POST /graph/runs/stream` 返回 `text/event-stream`，帧格式 `event: <type>\ndata: <json>` |
| 静态资源 | 不依赖前端；仅当 `frontend/dist` 恰好存在时顺带同源挂载（有存在性保护，可选） |

接口变更顺序：**先改本分支的 `app/schemas/agent.py` 契约 → 更新 `/openapi.json` 表现 → 再同步 `frontend` 分支的调用方**。

## 环境要求

- Python 3.12+（开发验证环境 3.14.6；`pyproject.toml` 声明 `requires-python >=3.14`，用 `uv sync` 时会按该声明约束）
- 不需要 Node.js；SQLite 内置，无外部数据库、无云服务
- 默认 `mock` 模式不联网、不消耗模型额度

## 快速开始

```bash
cd backend
python -m venv .venv
# Windows PowerShell：.venv\Scripts\Activate.ps1
# macOS / Linux / Git Bash：source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # PowerShell 用：Copy-Item .env.example .env
python -m uvicorn app.main:app --app-dir . --port 8000 --reload
```

也可以从仓库根启动：`python -m uvicorn app.main:app --app-dir backend --port 8000 --reload`。配置路径由 `Path(__file__).parents[2]` 定位到 `backend/`，不依赖启动时的工作目录。

首次启动的 lifespan 会自动重建元数据知识库并编译 LangGraph 状态图。自检：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

生成一份示例数据（便于在没有前端时验证全链路）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/datasets/demo \
  -H "Content-Type: application/json" -d '{"rows":48}'

curl -N -X POST http://127.0.0.1:8000/api/v1/graph/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"统计线上渠道的销售总额","dataset_id":"<上一步的 id>"}'
```

> 网络受限、无法 `pip install` 时，可把已有虚拟环境的 `site-packages` 加入 `PYTHONPATH` 再用系统 Python 启动；这是离线替代方案，不是项目依赖。

## 目录结构

```text
backend/
├── app/
│   ├── agent/          # LangGraph 状态、节点、图、逐节点事件流
│   ├── api/v1/         # health / datasets / agent / graph 路由
│   ├── clients/        # LLM、embedding、SQLite 客户端
│   ├── conf/           # 单一配置源（YAML + dataclass + Secrets）
│   ├── core/agent/     # 自研 ReAct 循环、规划器、护栏、记忆
│   ├── infra/          # 数据仓储、向量库、SQLite 连接
│   ├── models/  repositories/  services/   # 元数据表结构 / 仓储 / 业务逻辑
│   ├── prompt/         # 提示词模板加载器
│   ├── rag/            # 索引、检索、引用、embedder
│   ├── schemas/        # Pydantic 请求契约（对外契约的源头）
│   ├── skills/  mcp/  tools/   # 技能包、MCP client、确定性工具
│   └── main.py         # FastAPI 入口（lifespan 建知识库 + 编译图）
├── conf/               # app_config.yaml、meta_knowledge.yaml（非敏感参数）
├── prompts/            # 外置提示词模板
├── tests/              # 四套无需联网的回归脚本
├── requirements.txt / pyproject.toml
└── .env.example        # 环境变量样例（仅占位符）
```

## 环境变量

优先级：**环境变量 > `backend/.env` > `backend/conf/app_config.yaml`**。`.env` 已被忽略，密钥仅在内存中持有。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_MODE` | `mock` | `real` 才调用真模型；缺密钥自动降级为 mock |
| `ALIQWEN_API_KEY` | 空 | real 模式必需；兼容旧名 `aliQwen-api` |
| `ALIQWEN_BASE_URL` / `ALIQWEN_MODEL` | DashScope 兼容端点 / `qwen3.8-max` | OpenAI 兼容配置 |
| `AGENT_ENGINE` | `react` | 仅影响旧 `/runs`；`/graph/runs*` 始终走 LangGraph |
| `APP_DATA_DIR` / `APP_DB_PATH` | `./data` / 自动 | 数据目录与 SQLite 路径覆盖 |
| `AGENT_MAX_STEPS` 等 | 见 YAML | 护栏参数，如 `AGENT_MAX_ROWS=500` |

## 主要接口

统一前缀 `/api/v1`，完整定义见 `/docs`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health`、`/health/llm` | 健康检查 / 模型连通性自检 |
| POST | `/datasets` | 上传 CSV（`multipart` 字段 `file`，≤ 10 MB） |
| GET | `/datasets` | 数据集列表 |
| POST | `/datasets/demo` | 生成示例数据，`rows` 6–240 |
| POST | `/datasets/{id}/register` | 幂等重注册物理表并同步元数据 |
| GET | `/datasets/{id}/schema` / `stats` / `preview` | 执行靶 / 确定性统计 / 数据预览（`limit` ≤ 200） |
| DELETE | `/datasets/{id}` | 删除数据集 |
| POST | `/runs` | ReAct SSE 事件流 |
| POST | `/graph/runs` | LangGraph 同步运行，返回完整节点轨迹 |
| POST | `/graph/runs/stream` | LangGraph 逐节点 SSE：`meta → node×N → final → done` |

## 回归测试

测试使用临时 SQLite、固定 mock 模式，不联网、不碰项目主库：

```bash
cd backend
python tests/test_tools.py
python tests/test_agent_smoke.py
python tests/test_architecture.py
python tests/test_p1.py
```

## 当前边界

- 本地原型，不含部署、鉴权与多租户
- SQL 生成仍以确定性 mock 模板为主，真模型 function calling 与 `prompts/sql_correct.md` 纠错尚未接入
- 无问答金标准评测集；复杂查询的交叉校验会标注「未覆盖」，不谎称已校验
- 两套引擎端点并存，`AGENT_ENGINE` 只影响 `/runs`
- Skill / MCP / RAG 均为本地实现；向量检索使用本地哈希 embedding + SQLite
