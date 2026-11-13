# Insight Agent v2 · 前端工作台（`frontend` 分支）

前后端分离后的**前端独立工程视图**：本分支只包含 `frontend/`，不含任何后端源码。

| 分支 | 定位 |
| --- | --- |
| `main` | 全量集成基线，前后端都在，一次启动即可跑通全链路 |
| `backend` | 后端独立开发、测试与运行 |
| `frontend` | 本分支：前端独立开发、构建与预览 |

前端负责数据集选择与导入、对话式提问、结果卡（结论 / 指标 / 图表 / 表格 / SQL 摘要）、概览统计卡、数据预览，以及执行证据（节点时间线、召回证据、SQL 检查器、ReAct 轨迹）。**所有数字都由后端确定性计算，前端只负责渲染**。

## 与后端的协作契约

两侧不共享源码、依赖与构建流程，只通过下面这份 HTTP 契约协作：

| 项 | 约定 |
| --- | --- |
| API 前缀 | `/api/v1`，统一定义在 `src/api/client.js` 的 `BASE`，所有请求从这一个文件发出 |
| 开发代理 | `vite.config.js` 把 `/api` 代理到 `http://127.0.0.1:8000`（`changeOrigin: true`） |
| 后端地址 | 需先在 `8000` 启动后端；其 CORS 白名单只允许 `http://localhost:5173` / `http://127.0.0.1:5173` |
| 契约来源 | 后端 `GET /docs` 与 `/openapi.json`；请求体定义见后端 `app/schemas/agent.py` |
| 流式接口 | `POST /runs`、`POST /graph/runs/stream` 返回 `text/event-stream`；`client.js` 的 `consumeSSE` 按 `event:` / `data:` 拆帧 |
| 数据格式 | 仅交换 JSON 与 SSE 事件，不共享代码与依赖 |

接口变更顺序：**后端先改契约 → 前端同步 `src/api/client.js` 与结果视图**。若修改了后端端口，需同步 `vite.config.js` 的 proxy target。

## 环境要求

- Node.js 18+（Vite 5）
- 不需要 Python；后端是外部依赖，本分支不含其源码
- 开发期必须同时运行后端，单独启动前端只能看到界面，接口请求会失败

## 快速开始

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

构建与本地预览：

```bash
npm run build        # 产物 frontend/dist/
npm run preview
```

首次使用：在界面顶栏打开导入弹窗，选择「生成示例数据」或上传 CSV；随后直接提问，例如「统计线上渠道的销售总额」「帮我做异常识别」。

> 若改了后端端口，需同步 `vite.config.js` 的 proxy target；后端 CORS 白名单在后端分支的 `conf/app_config.yaml`。

## 目录结构

```text
frontend/
├── index.html
├── vite.config.js          # dev server 与 /api 代理
├── package.json / package-lock.json
└── src/
    ├── main.js
    ├── App.vue             # 三栏工作台、统计卡、对话、导入导出、双引擎切换
    ├── style.css           # 浅紫设计系统
    ├── api/client.js       # 全部 HTTP / SSE 调用（唯一与后端耦合的文件）
    └── components/
        ├── ChartView.vue       # 图表
        ├── NodeTimeline.vue    # LangGraph 节点时间线
        ├── RecallEvidence.vue  # 三路召回证据
        ├── SqlInspector.vue    # SQL 闭环与交叉校验
        └── TracePanel.vue      # ReAct 推理轨迹
```

## 前端调用的接口

所有函数导出自 `src/api/client.js`：

| 函数 | 端点 | 用途 |
| --- | --- | --- |
| `health` | `GET /health` | 引擎状态与工具列表 |
| `listDatasets` | `GET /datasets` | 侧栏数据集列表 |
| `createDemo` / `uploadDataset` | `POST /datasets/demo` / `/datasets` | 示例数据 / CSV 上传 |
| `previewDataset` | `GET /datasets/{id}/preview?limit=40` | 数据预览（上限 200 行） |
| `datasetStats` | `GET /datasets/{id}/stats` | 5 张概览统计卡 |
| `datasetSchema` | `GET /datasets/{id}/schema` | SQL 执行靶信息 |
| `runAgent` | `POST /runs`（SSE） | ReAct 链路 |
| `runGraphStream` | `POST /graph/runs/stream`（SSE） | LangGraph 逐节点链路（默认） |

## 界面能力

- 侧栏：数据集列表、分析历史（最近 12 条，可点击重跑）、引擎状态
- 顶栏：智能报告、导出（把结论 / SQL / 交叉校验写成 Markdown 下载）、导入数据
- 5 张统计卡：行数、数值字段、日期字段、缺失值、数据规模，数据来自后端 `stats` 接口
- 结果卡：意图标签、节点流水线、结论、指标、数据概览与质量、图表 / 表格、SQL 摘要
- 右侧「数据预览 / 执行证据」双 tab；证据 tab 保留时间线、召回证据、SQL 检查器、ReAct 轨迹
- 引擎切换 LangGraph / ReAct，分支可选 `sql` / `react` / 自动路由
- 结论徽标区分「确定性工具」与「模型增强」，避免把工具算出的结论误标为模型生成

## 当前边界

- 本地原型，无登录鉴权、无多租户、无独立部署配置
- 统计卡与预览完全依赖后端接口，前端不做抽样估算
- `frontend/dist/` 已忽略；构建产物可由后端同源挂载（可选，见 `backend` 分支 README）
