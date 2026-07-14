# BizSage3 — AI 运营诊断助手

面向 AI 编码助手的多端协同控制系统，连接 VS Code 插件、本地 Host 服务与 Android 客户端，实现 Agent 会话的移动端查看与远程控制。系统支持局域网配对、会话同步、流式输出展示、指令下发与审批确认，并通过统一协议模型与适配器机制兼容不同类型的 Agent 工具。

## 核心功能

- **会话管理** — VS Code 插件启动本地 Host 服务，完成 Agent 会话管理与移动端配对
- **移动端接入** — Android 端通过二维码或 pairing JSON 接入桌面端服务，查看会话列表、实时输出与状态变化
- **交互控制** — 移动端发送 Prompt、执行会话控制，并对高风险操作进行审批确认
- **多端同步** — 通过共享协议层与适配器机制实现多端消息同步、断线恢复及 Codex 等多 Agent 扩展
- **智能诊断** — 基于 LangGraph 构建的闭环工作流，自动识别行业场景、提取运营事实、评估信息完备度并生成结构化诊断报告

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI (Python 3.11+) |
| **AI 编排** | LangGraph + LangChain |
| **LLM** | OpenAI API (可替换) |
| **数据库** | SQLite (aiosqlite, 异步驱动) |
| **状态持久化** | LangGraph Checkpoint (SQLite) |
| **前端框架** | Next.js 15 (React 19, TypeScript) |
| **样式方案** | Tailwind CSS 4 |
| **Markdown 渲染** | react-markdown |

## 项目结构

```
BizSage3/
├── backend/                     # FastAPI 后端
│   └── app/
│       ├── main.py              # 应用入口 & 生命周期管理
│       ├── api.py               # REST API 路由（会话/消息/报告）
│       ├── api_schemas.py       # API 请求/响应 Schema
│       ├── models.py            # SQLAlchemy ORM 模型
│       ├── repository.py        # 数据访问层
│       ├── serializers.py       # ORM → API Schema 序列化
│       ├── config.py            # 环境配置（pydantic-settings）
│       ├── db.py                # 数据库连接
│       ├── domain/
│       │   ├── schemas.py       # 领域模型（场景识别、完备度评估等）
│       │   └── catalog.py       # 指标定义目录
│       └── services/
│           ├── workflow.py      # LangGraph 对话诊断工作流
│           └── model_service.py # LLM 模型调用封装
├── frontend/                    # Next.js 前端
│   └── src/
│       ├── app/
│       │   ├── layout.tsx       # 根布局
│       │   ├── page.tsx         # 首页
│       │   └── sessions/[sessionId]/page.tsx  # 诊断会话页（主工作区）
│       ├── components/
│       │   ├── AppShell.tsx     # 应用外壳布局
│       │   ├── SessionSidebar.tsx  # 会话列表侧边栏
│       │   ├── ChatPanel.tsx    # 对话面板
│       │   ├── ChatInput.tsx    # 消息输入框
│       │   ├── MessageBubble.tsx   # 消息气泡
│       │   ├── ReportView.tsx   # 诊断报告视图
│       │   ├── ProgressPanel.tsx   # 信息完备度进度面板
│       │   └── ErrorBanner.tsx  # 错误提示横幅
│       ├── hooks/
│       │   ├── useSessions.ts   # 会话列表状态管理
│       │   └── useDiagnosis.ts  # 诊断会话状态 & 消息交互
│       ├── lib/
│       │   └── api.ts           # 类型安全的 API 客户端
│       └── types/
│           └── index.ts         # TypeScript 类型定义
├── raw-docs/                    # 原始设计文档
└── CLAUDE.md                    # 项目开发指南
```

## LangGraph 工作流

诊断工作流由 6 个节点组成的有向图驱动：

```
START → scene_recognize（场景识别）
           ├─ 无行业 → greeting_guide（引导问候）→ await_input（等待输入）→ 重新识别
           └─ 有行业 → chat_extract（事实提取 + LLM 完备度评估）
                         → agent_reply（智能追问回复）
                         → await_input（等待输入）
                         → 循环回到 chat_extract
                         → 强制诊断 → generate_report（报告生成）→ END
```

### 关键设计

- **人机交互暂停** — 使用 LangGraph `interrupt()` 在信息收集与报告生成之间暂停，等待用户回复或确认
- **并发控制** — 基于 `asyncio.Lock` 的 per-session 锁防止同一会话重复提交
- **后台报告** — 报告生成独立于对话请求执行；单会话同时只允许一个任务，历史报告全部保留
- **幂等性保证** — 通过 `client_message_id` 唯一约束防止消息重复处理
- **状态持久化** — LangGraph Checkpoint 将图状态写入 SQLite，支持断线恢复和重放

## Docker Compose 部署

首次部署先创建后端环境文件，并至少填写 `OPENAI_API_KEY` 和 `ADMIN_TOKEN`：

```bash
cp backend/.env.example backend/.env
```

构建并启动服务：

```bash
docker compose up -d --build
docker compose ps
```

启动完成后访问 <http://localhost:3000>。FastAPI 不直接暴露到宿主机，前端会在
Compose 内部网络中将 `/api/*` 请求转发到后端。后端启动时会自动执行数据库迁移。

默认宿主机端口为 `3000`。如需修改，可在项目根目录创建 `.env`：

```dotenv
APP_PORT=8080
```

镜像构建默认使用清华 PyPI 和 npmmirror。如需切换到其他镜像，可在项目根目录的
`.env` 中覆盖：

```dotenv
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_REGISTRY=https://registry.npmmirror.com
```

Dockerfile 使用 BuildKit 缓存复用 pip、npm 和 Next.js 编译产物。日常更新直接执行
`docker compose up -d --build` 即可；不要常规添加 `--no-cache`，否则会跳过这些缓存。

常用运维命令：

```bash
docker compose logs -f
docker compose up -d --build   # 拉取代码后重新构建并重建服务
docker compose down            # 停止服务，保留数据
```

业务数据库和 LangGraph 检查点保存在 `bizsage-data` 命名卷中。仅在确认不再需要数据时
使用 `docker compose down -v`。HTTPS 反向代理部署时，还需在 `backend/.env` 中设置
`AUTH_COOKIE_SECURE=true`。

## 本地开发

### 环境要求

- Python 3.11+
- Node.js 20+
- OpenAI API Key

### 后端

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -e ".[dev]"

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY

# 升级数据库结构
alembic upgrade head

# 启动服务 (http://localhost:8000)
uvicorn app.main:app --reload
```

### 前端

```bash
cd frontend
npm install

# 启动开发服务器 (http://localhost:3000)
npm run dev
```

### API 端点概览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/sessions` | 获取会话列表 |
| `POST` | `/api/v1/sessions` | 创建新会话 |
| `GET` | `/api/v1/sessions/{id}` | 获取会话详情 |
| `DELETE` | `/api/v1/sessions/{id}` | 删除会话 |
| `POST` | `/api/v1/sessions/{id}/messages` | 发送消息 / 触发诊断 |
| `POST` | `/api/v1/sessions/{id}/reports` | 后台生成诊断报告；已有任务时返回 409 |
| `GET` | `/api/v1/sessions/{id}/reports` | 倒序获取全部诊断报告 |
| `GET` | `/api/v1/sessions/{id}/reports/{report_id}` | 获取指定诊断报告 |
| `GET` | `/api/v1/sessions/{id}/reports/{report_id}/download` | 下载指定 Markdown 报告 |

## 配置项

通过 `.env` 文件或环境变量配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | 主数据库连接 | `sqlite+aiosqlite:///bizsage.db` |
| `CHECKPOINT_DB_URL` | LangGraph 检查点数据库 | `sqlite+aiosqlite:///checkpoints.db` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | - |
| `OPENAI_BASE_URL` | API 基础 URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名称 | `gpt-3.5-turbo` |
| `COMPLETE_THRESHOLD` | 信息完备度阈值 | `80` |
| `CORS_ORIGINS` | 允许的前端域名 | `http://localhost:3000` |
| `ADMIN_TOKEN` | 服务端管理员令牌（必填） | - |
| `AUTH_SESSION_HOURS` | 登录会话有效时长 | `12` |
| `AUTH_COOKIE_SECURE` | 是否仅通过 HTTPS 发送登录 Cookie | `false` |

## 访问控制

启动 API 前，在 `backend/.env` 中设置 `ADMIN_TOKEN`。该值仅保留在服务端，用于
登录管理员界面。管理员可签发带有效期、可随时撤销的临时令牌；数据库只保存令牌的
SHA-256 摘要，完整令牌仅在创建成功时返回一次。

HTTPS 部署还需设置 `AUTH_COOKIE_SECURE=true`。更新后运行 `alembic upgrade head`
创建临时令牌表。

## License

Internal use.
