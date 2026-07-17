# BizSage3

BizSage3 是一个面向企业经营场景的 AI 运营诊断助手。它通过引导式对话了解业务现状，整理运营事实和信息缺口，并生成可追溯的诊断报告与改进建议。

## 核心能力

- **引导式运营诊断**：识别行业、子行业、业务模式和经营阶段；从对话中提取运营事实，评估信息完备度，并持续提出下一步问题。
- **流式对话与会话管理**：支持新建、切换和删除诊断会话；消息通过 SSE 流式返回，提供快捷回复，并以客户端消息 ID 保证幂等处理。
- **异步报告生成**：报告任务在后台执行，生成期间仍可继续对话；报告以 Markdown 保存和展示，支持历史查看与下载。信息不足时会明确标出结论局限。
- **行业知识库与引用**：管理员可维护带版本和标签的行业资料。已发布资料会参与诊断检索，报告和对话会展示经过服务端校验的引用证据。
- **可选公开网络检索**：配置 Tavily 或 Bing 凭据后可启用公开网络检索；默认关闭，不会因为缺少搜索凭据影响普通诊断。
- **访问控制**：管理员使用服务端令牌登录，可签发、撤销和删除临时访问令牌。普通用户的会话、消息和报告按令牌隔离。

## 诊断流程

```text
START -> scene_recognize
  |
  +-> 未识别或需澄清业务场景 -> greeting_guide -> await_input -> scene_recognize
  |
  +-> 已识别业务场景 -> conversation_turn -> await_input -> conversation_turn
                                                   |
                                                   +-> 请求生成报告 -> generate_report -> END
```

`conversation_turn` 会在一次回合内完成场景判断、事实提取、完备度评估、追问和快捷回复生成。诊断过程可按需使用已发布的行业知识库；公开网络检索仅在显式启用后可用。

## 架构

```text
Browser
  |
Nginx
  +-- Next.js frontend
  +-- FastAPI backend (3 replicas)
         |
         +-- PostgreSQL: 业务数据与 LangGraph checkpoint
         +-- Redis: 会话锁与 ARQ 任务队列
         +-- MinIO: 知识原件存储
         +-- Qdrant: 知识向量检索
         +-- OpenAI-compatible LLM and embedding APIs

ARQ report worker / knowledge worker
  +-- PostgreSQL, Redis, MinIO, Qdrant
```

| 层级 | 组件 |
| --- | --- |
| 前端 | Next.js 15、React 19、TypeScript、Tailwind CSS 4 |
| 后端 | FastAPI、SQLAlchemy Async、Alembic、Python 3.11+ |
| AI 工作流 | LangGraph、LangChain、OpenAI-compatible API |
| 数据与任务 | PostgreSQL、Redis、ARQ、MinIO、Qdrant |
| 部署入口 | Docker Compose、Nginx |

## 快速开始

推荐使用 Docker Compose 启动完整环境。需要 Docker Engine 或 Docker Desktop、Docker Compose v2，以及可用的 OpenAI-compatible API 凭据。

### 1. 配置后端凭据

从示例创建 `backend/.env`：

```powershell
# PowerShell
Copy-Item backend\.env.example backend\.env
```

```bash
# macOS/Linux/Git Bash
cp backend/.env.example backend/.env
```

至少填写以下两项：

```dotenv
OPENAI_API_KEY=your-api-key
ADMIN_TOKEN=use-a-long-random-admin-token
```

完整配置项见 [`backend/.env.example`](backend/.env.example)。使用 Compose 时，数据库、Redis、MinIO 和 Qdrant 的连接地址会由 [`compose.yaml`](compose.yaml) 覆盖为容器内地址。

### 2. 配置 Compose 密码

在仓库根目录新建 `.env`。这个文件没有模板，不应在生产环境中使用 Compose 内置的示例密码：

```dotenv
POSTGRES_PASSWORD=use-a-long-random-postgres-password
MINIO_ROOT_USER=bizsage-minio
MINIO_ROOT_PASSWORD=use-a-long-random-minio-password
APP_PORT=3000
```

`APP_PORT` 可改为其他宿主机端口，例如 `8080`。

### 3. 构建并启动

在仓库根目录执行：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

首次启动时，`migrate` 服务会执行数据库迁移和 LangGraph checkpoint 初始化。它成功后显示 `Exited (0)` 是正常状态；API 和 Worker 会等待迁移完成再启动。

打开 `http://localhost:3000/login`，使用 `ADMIN_TOKEN` 登录。若修改了 `APP_PORT`，请替换 URL 中的端口。

### 4. 验证服务

```bash
docker compose ps
docker compose logs migrate --tail=100
docker compose logs backend report-worker knowledge-worker --tail=100
curl -fsS http://localhost:3000/nginx-health
```

默认只有 Nginx 对宿主机暴露端口。后端的 `/health/live` 和 `/health/ready` 适合直接暴露 API 的开发或运维环境使用；`/health/ready` 会检查 PostgreSQL 和 Redis。

## 使用与管理

### 访问令牌

管理员使用 `ADMIN_TOKEN` 登录后，可在管理区创建带有效期的临时访问令牌。完整临时令牌只在创建时返回一次，数据库仅保存其 SHA-256 摘要。撤销或删除令牌不会删除既有会话；相关历史会话会转为仅管理员可见。

### 行业知识库

管理员可上传 DOCX、Markdown 或 TXT 文件，单个文件最大 20 MB。资料可按行业、子行业、业务模式和经营阶段加标签，并经过异步解析、分块和向量化后发布。只有有效的已发布版本参与检索；撤回后不再向诊断对话和报告提供内容。

默认使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `text-embedding-3-small` 生成嵌入。可通过 `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSIONS` 单独配置。变更向量维度后需要重建知识向量。

### 可选公开网络检索

要启用公开网络检索，在 `backend/.env` 中设置：

```dotenv
WEB_SEARCH_ENABLED=true
TAVILY_API_KEY=your-tavily-key
# 或配置 BING_SEARCH_API_KEY
```

可用提供商、超时和结果数量等完整配置见 [`backend/.env.example`](backend/.env.example)。

## 开发与检查

后端测试：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

前端静态检查与生产构建：

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

后端在宿主机直接运行时，需要先按 `backend/.env` 配置可访问的 PostgreSQL、Redis、MinIO 和 Qdrant：

```bash
cd backend
uvicorn app.main:app --reload
```

前端开发服务器默认将 `/api/*` 转发到 `http://localhost:8000`：

```bash
cd frontend
npm run dev
```

## 运维说明

```bash
docker compose up -d --build      # 更新代码后重新构建并启动
docker compose logs -f            # 跟踪全部服务日志
docker compose down               # 停止服务，保留数据卷
docker compose down --volumes     # 删除 PostgreSQL、Redis、MinIO、Qdrant 数据
```

清空知识原件和向量是破坏性操作，仅在已确认不再需要这些资料时执行：

```bash
docker compose run --rm backend python -m app.maintenance reset-knowledge --confirm-reset
```

公网部署应在负载均衡器、CDN 或入口网关终止 TLS，并在 `backend/.env` 中设置：

```dotenv
AUTH_COOKIE_SECURE=true
```

构建镜像默认使用清华 PyPI 与 npmmirror。必要时可在根目录 `.env` 中通过 `PIP_INDEX_URL` 和 `NPM_REGISTRY` 覆盖。

## 设计文档

- [行业知识库与引用展示设计方案](docs/BizSage3-行业知识库与引用展示设计方案.md)
- [PostgreSQL 与分布式任务架构迁移方案](docs/BizSage3-PostgreSQL与分布式任务架构迁移方案.md)
- [运营诊断 Agent 工作流原始设计](raw-docs/运营诊断Agent%20LangGraph闭环工作流%20核心实现代码（详细注释）.md)

## License

Internal use.
