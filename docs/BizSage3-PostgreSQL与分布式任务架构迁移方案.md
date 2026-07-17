# BizSage3 PostgreSQL 与分布式任务架构迁移方案

**文档类型**：技术架构与迁移方案  
**适用范围**：主业务数据库、LangGraph 检查点、后台任务、知识入库、报告生成和多实例部署  
**目标环境**：单机 Docker Compose，3 个后端 API 实例  
**容量假设**：约 1000 名同时在线用户，请求较稀疏  
**状态**：已实现，待 Docker 环境部署验证  
**日期**：2026-07-16

## 1. 方案结论

BizSage3 的主业务数据库和 LangGraph 检查点统一迁移到 PostgreSQL，并使用两个独立逻辑数据库：

- `bizsage`：业务数据、会话、消息、报告、知识库元数据、任务状态和管理审计。
- `bizsage_checkpoint`：LangGraph 工作流检查点。

新增 Redis 和独立后台 Worker：

- Redis 负责后台任务投递和跨 API 实例的会话互斥锁。
- PostgreSQL 中的任务记录始终是任务状态的唯一事实来源。
- Report Worker 负责报告生成。
- Knowledge Worker 负责知识解析、嵌入和 Qdrant 索引。

主业务流程不再依赖 SQLite。迁移采用全新空库，不迁移现有 `bizsage.db` 和 `checkpoints.db` 数据；维护窗口内同时清空 MinIO 知识桶和 Qdrant 知识集合。

## 2. 已确认决策

| 决策项 | 结论 |
| --- | --- |
| 主业务数据库 | PostgreSQL，不采用 MySQL |
| 业务数据迁移 | 不迁移，创建全新空库 |
| LangGraph 检查点 | 迁移到 PostgreSQL |
| 后端实例数 | 3 个 API 容器 |
| 部署方式 | 单机 Docker Compose 扩容 |
| 用户规模 | 约 1000 人同时在线，请求较稀疏 |
| 分布式协调 | Redis |
| 后台任务 | 独立 Worker |
| 旧知识数据 | 允许清空 MinIO 知识桶和 Qdrant 集合 |
| 检索审计 | 取消 `knowledge_retrieved` |
| 管理审计 | 保留上传、发布、撤销、预览、下载和入库等审计 |

## 3. 当前问题

### 3.1 SQLite 并发写限制

SQLite 即使启用 WAL，也只允许一个写事务。当前对话、报告、知识入库和管理操作共用 `bizsage.db`，并发写入容易产生 `database is locked`。

已取消 `knowledge_retrieved` 检索审计，避免对话请求持有写事务时，检索服务通过第二个数据库会话同步写审计造成确定性自锁。但其他长事务仍可能阻塞并发写操作。

### 3.2 长事务包含外部调用

当前知识上传和入库流程存在以下事务边界问题：

- 上传流程在数据库 `flush` 后等待 MinIO 上传。
- 入库流程在写入知识片段后等待嵌入服务和 Qdrant。
- 对话请求保存用户消息后，直到 LangGraph 和 LLM 调用结束才提交。

迁移到 PostgreSQL 后虽然不再有 SQLite 的全库单写限制，但长事务仍会占用连接、持有行锁并增加死锁和故障恢复成本，因此必须同步拆分。

### 3.3 进程内任务和锁无法跨实例协调

当前会话锁、报告任务和知识入库任务保存在单个 Python 进程内。扩容到 3 个 API 容器后会出现：

- 同一会话的两个请求可能由不同实例同时处理。
- 多个实例可能重复领取同一个知识入库任务。
- API 容器重启会中断其进程内报告或入库任务。
- 无法统一限制 LLM、嵌入服务和 Qdrant 的后台并发量。

## 4. 目标架构

```text
                           +--> API 1 --+
客户端 --> Nginx ----------+--> API 2 --+----> PostgreSQL
                           +--> API 3 --+       |- bizsage
                                |               `- bizsage_checkpoint
                                |
                                v
                              Redis
                         任务队列 + 会话锁
                                |
                    +-----------+-----------+
                    |                       |
                    v                       v
              Report Worker          Knowledge Worker
                    |                       |
                    v                       v
                   LLM          MinIO / Embedding / Qdrant
```

职责边界：

| 组件 | 职责 |
| --- | --- |
| Nginx | API 负载均衡、SSE 代理、前端代理 |
| API | HTTP/SSE、鉴权、输入校验、短事务持久化、任务投递 |
| PostgreSQL | 业务数据、工作流检查点、任务权威状态、管理审计 |
| Redis | 分布式会话锁、任务队列、短期协调状态 |
| Report Worker | 知识检索、LLM 报告生成、报告和证据持久化 |
| Knowledge Worker | 文件解析、嵌入生成、Qdrant 写入、入库状态更新 |
| MinIO | 知识原始文件存储 |
| Qdrant | 已发布知识片段的向量召回 |

## 5. PostgreSQL 设计

### 5.1 数据库划分

同一个 PostgreSQL 服务创建两个数据库：

```text
PostgreSQL
  |- bizsage
  `- bizsage_checkpoint
```

建议连接配置：

```dotenv
DATABASE_URL=postgresql+asyncpg://bizsage_app:${POSTGRES_PASSWORD}@postgres:5432/bizsage
CHECKPOINT_DB_URL=postgresql://bizsage_checkpoint:${CHECKPOINT_PASSWORD}@postgres:5432/bizsage_checkpoint
```

`DATABASE_URL` 由 SQLAlchemy 和 Alembic 使用；`CHECKPOINT_DB_URL` 由 LangGraph PostgreSQL checkpointer 使用。两个账号仅授予各自数据库的必要权限。

### 5.2 SQLAlchemy 连接池

初始配置：

| 进程类型 | 实例数 | `pool_size` | `max_overflow` | 理论上限 |
| --- | ---: | ---: | ---: | ---: |
| API | 3 | 10 | 5 | 45 |
| Report Worker | 1 | 5 | 5 | 10 |
| Knowledge Worker | 1 | 5 | 5 | 10 |

建议 PostgreSQL 初始设置 `max_connections=150`，为 LangGraph checkpointer、迁移、健康检查和运维连接保留余量。连接池启用 `pool_pre_ping`，并配置合理的连接回收时间。

1000 名在线用户不对应 1000 个数据库连接。API 在外部调用期间必须释放业务事务和连接，连接池只服务短时间数据库操作。

### 5.3 数据库保护参数

建议配置：

- `idle_in_transaction_session_timeout`：终止意外长期空闲事务。
- `statement_timeout`：限制异常 SQL，不覆盖正常的迁移任务。
- `lock_timeout`：避免请求无限等待行锁。
- 慢查询日志：记录超过阈值的 SQL。

具体数值应在压测后调整，不能用数据库超时替代正确的事务拆分。

### 5.4 迁移管理

- PostgreSQL 表结构只通过 Alembic 创建和升级。
- 移除应用启动时的 `Base.metadata.create_all()`。
- 移除或隔离 `PRAGMA journal_mode=WAL` 等 SQLite 专用语句。
- Docker Compose 增加一次性 `migrate` 服务。
- API 和 Worker 必须等待 `migrate` 成功完成后启动。
- 3 个 API 实例不得各自执行 `alembic upgrade head`。

## 6. LangGraph 检查点迁移

当前 `AsyncSqliteSaver` 替换为 `AsyncPostgresSaver`，检查点写入 `bizsage_checkpoint`。

迁移要求：

- 添加 `langgraph-checkpoint-postgres` 和对应的 Psycopg 3 依赖。
- 检查点初始化由一次性初始化步骤完成，避免 3 个 API 同时初始化表结构。
- 每个 API 实例使用独立连接或受控连接池访问同一个检查点数据库。
- 不迁移旧 `checkpoints.db`，新环境不恢复旧对话工作流。
- 下一轮请求可以落到任意 API 实例，不要求粘性会话。

业务数据和检查点使用不同数据库，便于单独清理、监控和限制权限，但仍由同一 PostgreSQL 服务统一运维。

## 7. Redis 与分布式会话锁

### 7.1 Redis 定位

Redis 不是业务事实来源，只承担：

- 同一会话的跨实例互斥锁。
- Report 和 Knowledge 后台任务投递。
- 短期任务协调和限流状态。

Redis 启用 AOF 持久化和健康检查。即使 Redis 中的任务消息丢失，PostgreSQL 中的 `queued` 任务仍可被协调器重新投递。

### 7.2 会话锁

会话锁键建议为：

```text
lock:session:{session_id}
```

锁必须具备：

- 随机持有者令牌。
- 有限 TTL，防止实例崩溃后永久锁定。
- 长请求期间定期续期。
- 使用原子脚本校验持有者后释放。
- PostgreSQL 唯一约束作为最后一道一致性保护。

同一会话已有请求运行时，新请求返回 `409 Conflict`。不同会话可以并行处理。

## 8. 独立后台 Worker

建议采用支持原生异步任务的 Redis 队列库，初始实现以 ARQ 为基线。API 和 Worker 使用同一个后端镜像，通过不同启动命令区分角色。

### 8.1 Worker 划分

| Worker | 初始实例数 | 初始并发 | 任务 |
| --- | ---: | ---: | --- |
| Report Worker | 1 | 4 | 报告知识检索、LLM 调用、报告保存 |
| Knowledge Worker | 1 | 2 | 文件解析、嵌入调用、Qdrant 索引 |

并发上限应根据 LLM 和嵌入服务的配额、响应时间和失败率调整，而不是跟随在线用户数线性增长。

### 8.2 任务状态

Redis 队列按“至少一次”语义设计，任务处理必须幂等。

知识入库继续使用 `knowledge_ingestion_jobs` 保存权威状态。报告生成建议新增 `report_generation_jobs`，至少包含：

```text
id
session_id
state               queued | running | completed | failed
attempt_count
error
queued_at
started_at
finished_at
worker_id
created_at
updated_at
```

PostgreSQL 使用条件更新原子领取任务。相同任务即使被 Redis 重复投递，也只有一个 Worker 能从 `queued` 转为 `running`。

定时协调任务负责：

- 重新投递仍为 `queued` 但 Redis 中缺失的任务。
- 将超过租约时间的 `running` 任务恢复为可重试状态。
- 对超过最大重试次数的任务标记 `failed`。
- 记录任务延迟、执行时间和失败原因。

## 9. 事务边界优化

### 9.1 对话请求

```text
获取 Redis 会话锁
  -> 短事务：幂等校验、保存用户消息、提交
  -> 无业务数据库事务：LangGraph、LLM、搜索工具、SSE 处理
  -> 短事务：保存会话状态和助手消息、提交
  -> 释放 Redis 会话锁
```

异常处理使用独立短事务更新失败状态。任何 LLM 或网络等待期间都不得保留业务数据库写事务。

### 9.2 知识上传

```text
读取并校验上传文件
  -> 在应用层生成 document_id/version_id
  -> 上传原文件到 MinIO
  -> 短事务：写文档、版本、入库任务和 document_uploaded/version_uploaded 审计
  -> 提交
  -> 投递 Knowledge Worker 任务
```

如果数据库提交失败，执行 MinIO 对象补偿删除；补偿失败的对象由定期孤儿清理任务处理。Redis 投递失败时保留数据库中的 `queued` 记录，由协调器补投。

### 9.3 知识入库

```text
短事务：原子领取任务并标记 running
  -> 无数据库事务：读取 MinIO、解析、切片、调用嵌入服务
  -> 短事务：写入/替换知识片段并记录索引中间状态
  -> 无数据库事务：写入 Qdrant
  -> 短事务：版本改为 pending_review、任务改为 completed、写 ingestion_completed 审计
```

Qdrant 写入失败时按 `version_id` 清理未完成向量，并用短事务记录任务失败和 `ingestion_failed` 审计。未发布版本不会被正常检索返回。

### 9.4 报告生成

```text
API 短事务：创建 report_generation_job
  -> 投递 Report Worker
  -> Worker 短事务：原子领取任务
  -> 无数据库事务：知识检索、LLM 报告生成
  -> 短事务：保存报告、证据、report_evidence_persisted 审计和任务完成状态
```

报告任务以 `job_id` 幂等；同一会话只允许一个 `queued/running` 报告任务，可使用 PostgreSQL 部分唯一索引约束。

### 9.5 发布和撤销

发布和撤销的数据库状态及管理审计继续在同一短事务中提交。Qdrant 激活、停用或删除通过可重试任务执行。

关系数据库仍负责最终授权校验：即使 Qdrant 短期存在旧向量，已撤销版本也不能进入最终检索结果。

## 10. 审计策略

保留以下管理和系统审计：

- `document_uploaded`
- `version_uploaded`
- `ingestion_retried`
- `version_published`
- `version_revoked`
- `vector_sync_failed`
- `original_previewed`
- `original_downloaded`
- `ingestion_completed`
- `ingestion_failed`
- `report_evidence_persisted`

取消 `knowledge_retrieved` 检索审计。检索不再产生独立数据库写操作。

所有保留审计必须与对应业务状态在同一个短事务内提交。审计失败时整个管理操作回滚，避免业务状态与管理审计不一致。

## 11. Docker Compose 调整

目标服务：

```text
postgres
redis
migrate
backend        x3
report-worker  x1
knowledge-worker x1
frontend
nginx
minio
qdrant
```

关键要求：

- PostgreSQL 使用独立持久卷 `postgres-data`。
- Redis 使用独立持久卷并启用 AOF。
- `migrate` 成功后 API 和 Worker 才能启动。
- 后端通过 `docker compose up --scale backend=3` 扩容。
- 后端服务不直接映射宿主机端口，只由 Nginx 访问。
- Nginx 使用 Docker DNS 动态解析后端实例，避免容器替换后继续访问旧 IP。
- SSE 代理关闭响应缓冲，并设置覆盖正常 LLM 请求时长的读取超时。
- API 和 Worker 使用相同应用镜像，但启动命令不同。

当前 Dockerfile 中“每个后端启动前执行 Alembic”的方式必须拆除，迁移只能由 `migrate` 服务执行一次。

## 12. 依赖调整

计划新增：

- `asyncpg`：SQLAlchemy PostgreSQL 异步驱动。
- `langgraph-checkpoint-postgres`：LangGraph PostgreSQL checkpointer。
- `psycopg` 与连接池扩展：checkpointer 使用。
- `redis`：异步 Redis 客户端。
- `arq`：异步后台任务队列。

计划保留测试所需的 SQLite/aiosqlite 支持时，应让 SQLite 专用配置仅在测试环境生效；生产路径不得执行 SQLite PRAGMA。

## 13. 实施阶段

### 阶段 1：PostgreSQL 基础设施

1. 增加 PostgreSQL 服务、初始化脚本、账号和两个数据库。
2. 增加 `asyncpg`，调整 SQLAlchemy 引擎和连接池。
3. 校验现有 Alembic 迁移在全新 PostgreSQL 上可完整执行。
4. 移除运行时 `create_all()` 和 SQLite WAL 配置。
5. 增加一次性 `migrate` 服务。

### 阶段 2：LangGraph PostgreSQL 检查点

1. 替换 `AsyncSqliteSaver`。
2. 增加检查点初始化流程。
3. 验证请求在不同 API 实例之间切换后仍能恢复同一工作流。

### 阶段 3：Redis 和多实例会话锁

1. 增加 Redis 服务和客户端封装。
2. 实现带 TTL、续期和安全释放的会话锁。
3. 保留数据库唯一约束和消息幂等校验。
4. 验证同一会话并发请求只允许一个执行。

### 阶段 4：Worker 和任务可靠性

1. 将报告生成迁移到 Report Worker。
2. 将知识入库迁移到 Knowledge Worker。
3. 新增报告任务表和任务协调器。
4. 实现任务原子领取、幂等、超时恢复和失败重试。
5. 移除 API 进程内 `asyncio.create_task()` 任务管理。

### 阶段 5：事务拆分

1. 拆分对话请求事务。
2. 将 MinIO 上传移出数据库事务。
3. 将嵌入和 Qdrant 操作移出数据库事务。
4. 保证管理审计与对应状态在短事务内原子提交。

### 阶段 6：Compose 扩容与切换

1. 调整 Nginx 动态服务发现和 SSE 配置。
2. 执行清库切换流程。
3. 启动 3 个 API 实例和两个 Worker。
4. 完成集成、故障和负载验证。

## 14. 清库切换步骤

> 警告：本节包含破坏性操作。只能在明确的维护窗口内执行，并在执行前验证备份。不得把清理命令作为普通应用启动逻辑。

1. 停止 Nginx 写入流量和所有旧 API/Worker。
2. 备份 `bizsage-data`、`minio-data` 和 `qdrant-data` Docker 卷。
3. 启动 PostgreSQL 和 Redis。
4. 运行 PostgreSQL 初始化和 Alembic 迁移。
5. 初始化 LangGraph checkpoint 表。
6. 使用显式、带确认参数的维护命令清空 MinIO 知识桶。
7. 使用显式、带确认参数的维护命令删除并重建 Qdrant 知识集合。
8. 启动 Report Worker 和 Knowledge Worker。
9. 启动 3 个 API 实例、前端和 Nginx。
10. 执行健康检查、烟雾测试和多实例一致性测试。
11. 保留旧 SQLite 和存储卷，直到新环境完成稳定性观察。

旧主库、旧检查点、旧 MinIO 知识文件和旧 Qdrant 向量不会进入新环境。所有旧会话、报告、令牌和知识资料均不可在新系统中继续使用。

## 15. 测试与验证

### 15.1 单元测试

- PostgreSQL URL、连接池和配置校验。
- Redis 会话锁获取、续期、超时和安全释放。
- Worker 任务状态机和重复投递幂等。
- 上传失败后的 MinIO 补偿逻辑。
- 管理审计与业务状态原子提交。
- 检索流程不写 `knowledge_retrieved`。

### 15.2 集成测试

- 在真实 PostgreSQL、Redis、MinIO 和 Qdrant 容器上运行。
- Alembic 可从空库升级到 `head`。
- LangGraph 检查点能被不同 API 实例恢复。
- 同一会话的两个并发请求中只有一个成功处理。
- Redis 重复投递不会产生重复报告或重复知识片段。
- Worker 重启后 `queued` 和超时 `running` 任务能够恢复。
- Qdrant 短期失败不会发布不完整知识版本。

### 15.3 负载与故障测试

- 模拟约 1000 个在线会话和稀疏请求。
- 对活动对话、报告和知识入库施加受控并发。
- 观察数据库池等待时间、活跃连接、事务时长和锁等待。
- 在任务执行中重启 API、Worker、Redis 和 Qdrant，验证恢复行为。
- 验证 SSE 长连接不会占用业务数据库事务。

## 16. 验收标准

迁移完成必须同时满足：

1. 运行时主业务数据和 LangGraph 检查点均不再使用 SQLite。
2. 3 个 API 实例均通过健康检查并由 Nginx 分发流量。
3. 同一会话不能被两个 API 实例同时处理。
4. LLM、MinIO、嵌入和 Qdrant 调用期间不存在业务数据库写事务。
5. 后台任务重复投递不会产生重复报告、重复片段或重复状态推进。
6. Worker 重启后未完成任务可自动恢复或明确失败。
7. `knowledge_retrieved` 不再写入，其他管理审计正常保存。
8. PostgreSQL 连接使用量在设计预算内，无持续连接池等待。
9. 新环境的 MinIO 知识桶和 Qdrant 集合为空，并可完成一次完整上传、入库、发布和检索闭环。
10. 完整后端测试、集成测试和多实例故障测试通过。

## 17. 监控建议

至少采集以下指标：

- PostgreSQL 活跃连接、连接池等待、事务时长、锁等待和慢查询。
- Redis 内存、连接数、队列长度和任务等待时间。
- 各 Worker 活跃任务数、执行耗时、重试次数和失败率。
- LLM 和嵌入服务延迟、限流率和错误率。
- MinIO 与 Qdrant 请求延迟和失败率。
- API 请求量、SSE 活跃数、会话锁冲突数和 `409` 数量。

日志必须包含 `request_id`、`session_id`、`job_id` 和 `worker_id`，但不得记录令牌、密钥或完整敏感业务输入。

## 18. 风险与回退

| 风险 | 缓解措施 |
| --- | --- |
| PostgreSQL 或 Redis 启动失败 | 健康检查、启动依赖、明确错误日志 |
| 迁移由多个实例重复执行 | 独立一次性 `migrate` 服务 |
| Redis 任务丢失 | PostgreSQL 任务状态为事实来源，协调器补投 |
| Worker 重复执行 | 原子领取、幂等键、唯一约束 |
| Redis 锁过期导致并发处理 | TTL 续期、持有者校验、数据库约束兜底 |
| MinIO 成功但数据库失败 | 补偿删除和孤儿对象清理 |
| Qdrant 与数据库短暂不一致 | 数据库状态最终校验、重试和按版本清理 |
| 新环境验证失败 | 停止新栈，恢复旧 Compose 和已备份卷 |

回退到旧环境会丢弃切换后写入新 PostgreSQL 的数据，因此正式切换前必须完成烟雾测试；正式开放流量后如需回退，应先导出或明确放弃新环境数据。

## 19. 非目标

本次方案不包含：

- PostgreSQL 高可用或多机容灾；当前仍是单机部署。
- Kubernetes 改造。
- 旧 SQLite、MinIO 或 Qdrant 数据迁移。
- 新增审计查询页面。
- 恢复 `knowledge_retrieved` 检索审计。
- 根据 1000 名在线用户直接创建 1000 个数据库连接。
