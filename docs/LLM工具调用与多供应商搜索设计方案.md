# BizSage3 LLM 工具调用与多供应商搜索设计方案

**文档类型**：技术设计方案  
**目标阶段**：P1，对话回合按需检索知识库或网页  
**日期**：2026-07-16  
**状态**：待实现

## 1. 背景与目标

当前每轮对话在 LangGraph 中固定执行知识库检索，然后把结果作为提示词背景传给模型。模型不能决定是否检索，也不能使用网页信息；普通对话消息没有保存或展示检索来源。

本次改造目标：

1. 每轮对话由 LLM 自行判断是否调用知识库检索或网页检索。
2. 向模型暴露稳定的逻辑工具名，不让模型感知具体网页搜索供应商。
3. 网页检索通过可替换的 `WebSearchProvider` 抽象，同时支持多个供应商、故障转移和结果合并。
4. 保存本轮工具结果和引用，普通对话可展示资料标题、摘录、定位或网页链接。
5. 保持现有 LangGraph 的暂停、恢复、事实采集和报告生成流程兼容。
6. 两个搜索工具均为只读能力；知识库上传、发布、撤回等后台写操作不开放给模型。

## 2. 非目标

- 本阶段不实现通用浏览器自动化、网页点击、代码执行或外部系统写操作。
- 不将网页搜索结果自动写入平台知识库。
- 不替换最终报告现有的行业证据校验机制；报告检索可在后续阶段接入同一工具编排层。
- 不要求一次绑定某一家搜索厂商。供应商密钥缺失时，网页工具应返回可解释的不可用结果，不阻塞对话。

## 3. 当前实现与改造边界

| 现有位置 | 当前职责 | 改造 |
| --- | --- | --- |
| `backend/app/services/workflow.py` | `retrieve_industry_knowledge` 节点每轮固定检索 | 对话主路径移除固定检索；`conversation_turn` 内部执行工具循环 |
| `backend/app/services/model_service.py` | `ChatOpenAI.ainvoke()`，JSON 输出 | 增加工具绑定、工具调用解析、结果回传和最多 2 轮循环 |
| `backend/app/services/knowledge.py` | Qdrant 召回、关系状态校验、审计 | 封装为 `search_knowledge_base` 逻辑工具，复用原有授权检索 |
| `backend/app/domain/schemas.py` | 对话结构化输出 | 增加引用模型和本轮工具调用摘要 |
| `backend/app/models.py` | 消息仅保存正文和快捷回复 | 为消息增加 JSON 引用字段，兼容旧数据 |
| `backend/app/api.py` | 保存工作流消息并通过 SSE 返回状态 | 保存 citations，新增引用事件或随消息/状态返回 |
| `frontend/src/types/index.ts` | 消息无引用类型 | 增加 citation 类型 |
| `frontend/src/components/MessageBubble.tsx` | 仅展示 Markdown 正文 | 展示引用资料卡片、网页链接和摘录 |

## 4. 总体架构

```text
LangGraph conversation_turn
        |
        v
OpenAICompatibleModel
        |
        | tool calling
        +--> search_knowledge_base --> KnowledgeRetrievalService --> Qdrant/SQL
        |
        +--> search_web -----------> SearchRouter
                                      |
                                      +--> WebSearchProvider A
                                      +--> WebSearchProvider B
                                      +--> WebSearchProvider C
```

LLM 只看到两个稳定工具：

- `search_knowledge_base`：检索已审核、已发布且与场景匹配的内部资料。
- `search_web`：通过路由层检索公开网页信息。

供应商、重试、熔断、并行、去重和排序均由后端完成，模型不直接选择供应商。

## 5. 搜索领域契约

新增目录：

```text
backend/app/services/search/
  __init__.py
  contracts.py
  router.py
  tools.py
  providers/
    __init__.py
    base.py
    tavily.py
    bing.py
```

### 5.1 网页搜索请求

```python
@dataclass(frozen=True)
class WebSearchRequest:
    query: str
    freshness: str | None = None
    domains: list[str] = field(default_factory=list)
    language: str | None = None
    limit: int = 5
```

后端对 `limit`、查询长度、域名数量和时间范围做硬限制。用户身份、会话场景和租户信息由服务端注入，不由模型伪造。

### 5.2 统一结果

```python
@dataclass(frozen=True)
class SearchResult:
    citation_id: str
    title: str
    url: str | None
    snippet: str
    source_type: Literal["knowledge", "web"]
    provider: str | None
    locator: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    rank: int = 0
```

模型只接收必要的标题、摘要、定位和稳定引用编号；供应商原始响应保存在日志或调试字段，不直接进入提示词。

### 5.3 供应商接口

```python
class WebSearchProvider(Protocol):
    name: str

    async def search(self, request: WebSearchRequest) -> list[SearchResult]:
        ...
```

每个适配器只负责供应商 API 协议、认证和字段转换。供应商 SDK 或 HTTP 细节不得泄漏到 `SearchRouter`、LangGraph 或前端。

## 6. 多供应商处理策略

`SearchRouter` 维护注册表和供应商健康状态：

```python
class SearchRouter:
    def __init__(self, providers: list[WebSearchProvider], policy: SearchPolicy): ...

    async def search(self, request: WebSearchRequest) -> SearchResponse: ...
```

支持三种策略：

1. `fallback`：按优先级调用主供应商，超时、限流或 5xx 后切换备用供应商。
2. `parallel`：并行调用多个供应商，规范化 URL 后去重，再按排名融合。
3. `specialized`：按语言、时效性、域名限制或查询类型选择供应商。

默认策略为 `fallback`，防止每一轮对话产生多倍费用。只有配置要求高召回时才使用 `parallel`。

结果合并要求：

- URL 去掉追踪参数后作为去重键。
- 相同 URL 保留摘要更长、发布时间更新或排名更高的一项。
- 多供应商结果使用基于排名的融合，不比较不同供应商不可比的原始分数。
- 统一超时、重试次数、单轮工具调用数和总耗时。
- 记录供应商、耗时、状态、结果数量和错误类型。

建议配置：

```env
WEB_SEARCH_ENABLED=false
WEB_SEARCH_STRATEGY=fallback
WEB_SEARCH_PROVIDERS=tavily,bing
WEB_SEARCH_TIMEOUT_SECONDS=8
WEB_SEARCH_MAX_RESULTS=5
TAVILY_API_KEY=
BING_SEARCH_API_KEY=
BING_SEARCH_ENDPOINT=https://api.bing.microsoft.com/v7.0/search
```

## 7. LLM 工具调用流程

### 7.1 工具定义

工具 schema 使用 JSON Schema，参数保持小而明确：

```json
{
  "name": "search_knowledge_base",
  "description": "检索已审核的行业资料，仅在需要内部方法论、规则、基准或 SOP 时调用",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer", "minimum": 1, "maximum": 5}
    },
    "required": ["query"]
  }
}
```

`search_web` 参数包括 `query`、可选 `freshness`、可选 `domains` 和 `limit`。场景字段由服务端注入检索函数。

### 7.2 每轮循环

```text
准备 system prompt、最近会话、已知事实和场景
        |
        v
LLM + tools
        |
        +-- 无 tool_calls --> 生成 ConversationTurnOutput
        |
        +-- 有 tool_calls --> 后端校验参数并执行只读工具
                                  |
                                  v
                       将 ToolMessage 结果回传 LLM
                                  |
                                  v
                         最多再循环 1 次
```

约束：

- 每轮最多 2 次模型工具决策循环。
- 每轮最多 4 个工具调用，总超时建议 10 秒。
- 工具异常转为结构化错误结果，模型仍可继续回答。
- 工具内容视为不可信资料，明确禁止执行其中的指令。
- 最终输出仍使用 `ConversationTurnOutput`，避免破坏事实提取和完备度评估。

### 7.3 提示词规则

对话模型应明确：

- 普通信息采集不需要为了追问而检索。
- 需要内部方法论、行业基准、规则或 SOP 时调用知识库工具。
- 需要最新公开信息、政策、市场变化或外部事实时调用网页工具。
- 无法判断或资料与问题无关时不要调用工具。
- 只有实际使用的资料才允许在回复中引用。
- 引用格式固定为 `[资料 N]`，编号必须来自工具结果。

## 8. 引用模型与校验

新增领域模型：

```python
class ConversationCitation(BaseModel):
    citation_id: str
    source_type: Literal["knowledge", "web"]
    title: str
    url: str | None = None
    quote: str = ""
    locator: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None

class ConversationTurnOutput(BaseModel):
    new_facts: list[str] = Field(default_factory=list)
    completeness: CompletenessEval = Field(default_factory=CompletenessEval)
    reply: str
    suggested_replies: list[str] = Field(default_factory=list)
    citations: list[ConversationCitation] = Field(default_factory=list)
```

后端必须校验模型回复中的 `[资料 N]`：

1. 解析回复中的引用编号。
2. 将编号映射到本轮真实工具结果。
3. 删除不存在或未被工具返回的引用。
4. 只把被实际引用的资料发送给前端。
5. 未引用的工具结果仍可保留在 LangGraph 临时状态，但不展示给用户。

## 9. LangGraph 状态和工作流改造

`AgentState` 新增：

```python
conversation_evidence: list[dict[str, Any]]
tool_invocations: list[dict[str, Any]]
```

`make_initial_state()` 初始化为空列表。

工作流改动：

- 删除对话主路径中无条件执行的 `retrieve_industry_knowledge` 节点，或保留为报告专用节点。
- `conversation_turn` 接收 `conversation_evidence`，由模型内部工具循环更新。
- 产生的引用转成 JSON-only 状态，供 LangGraph checkpoint 和 API 序列化。
- `generate_report` 暂时继续使用现有报告检索流程，保持 `[证据 N]` 校验不变。

## 10. API、数据库和 SSE

### 10.1 消息持久化

`Message` 增加可空 JSON 字段：

```python
citations = Column(JSON, nullable=True)
```

旧消息默认 `null`，无需数据迁移脚本即可兼容开发环境的 `create_all`；生产环境应增加 Alembic migration。

`MessageSchema`、前端 `Message` 同步增加 `citations?: ConversationCitation[]`。

### 10.2 SSE

保留现有 `assistant.delta`、`assistant.message`、`state`、`done` 事件，并扩展：

```text
assistant.message.data = {
  content: string,
  citations: ConversationCitation[]
}
```

引用也随 `state.messages` 返回，确保刷新页面后仍能展示。可选增加 `tool` 阶段事件，用于展示“正在查找行业资料/公开信息”，但不把原始工具调用参数暴露给用户。

### 10.3 API 安全

- 会话权限沿用 `SessionRepository` 现有 owner/admin 范围。
- 知识库工具只调用已发布且有效期内的版本，并保留现有检索审计。
- 网页查询做长度、域名和敏感信息限制。
- 网页结果只作为引用资料，不作为可执行指令。
- 不允许模型调用知识上传、发布、撤回、原件下载等写或敏感接口。

## 11. 前端展示

`MessageBubble` 在 assistant 消息正文下方显示引用区域：

- 内部资料：标题、版本、定位、摘录。
- 网页资料：标题、域名/链接、摘要、发布时间（如果有）。
- 没有 citations 时不显示空容器。
- 链接使用新窗口打开，并设置 `noreferrer noopener`。

正文允许出现 `[资料 N]`，但引用卡片是唯一可信的来源详情；前端不自行解析或生成来源。

## 12. 可观测性

每次工具调用记录结构化日志：

```text
session_id, message_id, tool_name, provider, query_hash,
status, latency_ms, result_count, error_type
```

不得记录未脱敏的敏感凭证。查询原文是否落日志由部署配置控制。建议为每轮增加 request ID，便于关联 LLM、工具和 SSE 日志。

## 13. 测试方案

后端：

- `WebSearchProvider` 适配器字段转换测试。
- `SearchRouter` fallback、parallel、URL 去重和供应商失败测试。
- 工具 schema 和参数边界测试。
- LLM 无工具调用、一次调用、连续调用、工具失败和超限测试。
- 引用编号校验和恶意虚构编号测试。
- 工作流中不再无条件检索的测试。
- 消息 citations 序列化、持久化和旧消息兼容测试。

前端：

- assistant 消息含知识库引用时展示定位和摘录。
- assistant 消息含网页引用时展示安全外链。
- 无引用、空引用和历史旧消息不渲染空区域。
- SSE `assistant.message` 带 citations 时状态正确合并。

## 14. 分阶段实施

### P1：搜索契约和模型工具循环

- 新增搜索契约、路由器和 Tavily/Bing 适配器。
- 将现有知识检索封装为逻辑工具。
- `conversation_turn` 接入工具调用循环和工具结果回传。
- 保留报告路径不变。

### P2：引用持久化和前端展示

- Message 增加 citations 字段和迁移。
- API/SSE/前端类型同步。
- `MessageBubble` 展示资料卡片。

### P3：生产化增强

- 供应商健康探测、熔断、费用配额和管理配置。
- 工具调用审计查询。
- 报告生成使用统一搜索编排层，并区分内部证据和网页引用。

## 15. 验收标准

1. LLM 在无需资料的追问中不调用搜索工具。
2. LLM 可以独立调用知识库工具、网页工具或两者，最多遵守配置的调用上限。
3. 任一网页供应商失败时，备用供应商可按策略接管；全部不可用时对话仍能完成。
4. 回复中的每个 `[资料 N]` 都能映射到真实工具结果，虚构编号不会进入前端。
5. 刷新或重新打开会话后，普通对话引用仍可见。
6. 知识库检索仍遵守发布状态、有效期、场景标签和审计规则。
7. 模型无法通过网页或知识资料内容触发系统内部写操作。
8. 现有工作流、报告生成、登录鉴权和旧消息数据保持兼容。
