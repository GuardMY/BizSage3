# BizSage3 对话测试分析报告

> 测试日期: 2026-07-24 | 会话 ID: `23cc3b6486c142cc8aa491d1dfebafa5`
> 模型: DeepSeek v4 Flash | 行业场景: 南方桉树林场经营诊断

---

## 一、测试概述

### 1.1 测试方法

- **用户侧**: 通过 DeepSeek v4 Flash 实时生成，角色为「南方5000亩桉树林场经营者」
- **助手侧**: BizSage3 通过 DeepSeek v4 Flash 实时生成（Factory: `OpenAICompatibleModel`）
- **会话轮数**: 22 轮对话 + 1 份诊断报告
- **LLM 总调用次数**: 65 次（4 次 JSON 场景识别 + 41 次工具调用 + 20 次最终 JSON 生成）

### 1.2 对话流程

```
START → scene_recognize (识别为林业/林场)
      → conversation_turn × 22轮
         ├── 每轮: Tool请求(可选) → JSON最终生成
         └── await_input → conversation_turn (循环)
      → generate_report (后台Worker)
      → END
```

---

## 二、对话质量分析

### 2.1 整体评价

对话整体流畅自然，助手能够：

| 维度 | 评分 | 说明 |
|------|------|------|
| 行业识别 | ⭐⭐⭐⭐⭐ | 首轮即准确识别「林业-林场-桉树种植」 |
| 追问质量 | ⭐⭐⭐⭐ | 问题逐层递进，从规模→成本→销售→机械化→转型 |
| 专业深度 | ⭐⭐⭐⭐ | 对桉树轮伐、分级销售、林下经济给出具体建议 |
| 自然度 | ⭐⭐⭐⭐ | 话术友好，emoji使用恰当，像懂行的朋友 |
| 信息采集效率 | ⭐⭐⭐⭐ | 22轮采集40条经营事实，完备度达85% |
| 冗余控制 | ⭐⭐⭐ | 部分轮次存在事实重复采集（见2.2） |

### 2.2 发现的问题

**问题1: 事实重复采集**

以下事实在日志中被重复记录（LLM在不同轮次输出了相同或高度相似的 new_facts）:
- 「桉树5年轮伐」出现 2 次
- 「利润率20%-25%」出现 2 次
- 「林下养蜂/菌菇」出现 3 次
- 「白蚁病虫害」出现 2 次

**根因**: `conversation_turn` 的 System Prompt 中 `existing_facts` 列表太长（40条），模型在长上下文中对已有事实的边界判断不够精确。

**问题2: 过早触发「完备度充足」标记**

从第7轮开始，几乎每轮回复末尾都出现 `**[信息已比较充分，点击按钮即可生成诊断报告]**`，但此时仍有大量维度未覆盖（碳汇、数字化、政策细节等）。

**根因**: 完备度阈值 80% 的触发条件过于宽松，模型在采集到基础经营数据后即判定为"足够"。

**问题3: 工具检索调用偏少**

22轮对话中仅触发少量知识库检索调用，大部分回复依赖模型本身的知识。在以下场景中模型未调用工具：
- 第11-13轮讨论木材分级销售策略时 → 应检索 benchmark_rule 类资料
- 第15轮讨论病虫害防治时 → 应检索 methodology 类资料
- 第18-19轮讨论林下养蜂时 → 应检索 case_sop 类资料

**根因**: System Prompt 中工具使用指导偏保守（"普通信息采集、场景澄清、闲聊、拒绝回答和人工请求不需要检索"），且工具返回内容标记为"不可信参考内容"可能导致模型不愿引用。

### 2.3 对话轮次关键指标

| 指标 | 数值 |
|------|------|
| 对话轮数 | 22 |
| 采集经营事实 | 40条 |
| 最终完备度 | 85% |
| 助手平均回复长度 | ~120字 |
| 用户平均回复长度 | ~50字 |
| 平均每轮延迟 | ~3-5秒 |
| 报告字数 | 3410字 |

---

## 三、LLM 调用日志分析

### 3.1 调用分布

```
总计 65 次 LLM 调用:

scene_recognize (场景识别):
  ├── JSON request:  2 次
  └── JSON response: 2 次

conversation_turn (对话回合):
  ├── Tool request:  41 次
  ├── Tool response: 41 次
  ├── 最终 JSON request:  20 次
  └── 最终 JSON response: 20 次

generate_report (生成报告):
  └── Chat request/response: 1 次 (Worker异步执行)
```

### 3.2 Prompt 结构分析

#### Scene Recognizer Prompt (~1200 tokens)

```
系统角色设定 (1行)
当前场景状态 (1行)
JSON Schema 定义 (15行)
decision 枚举含义 (5 × ~40字)
scene_action 枚举含义 (4 × ~40字)
行业识别规则 (5条)
回复规则 (6条)
```

**问题**: 此 Prompt 中约 **40% 的内容是 JSON Schema 和枚举解释**，而这些可以用 structured output / tool_choice 方式交给模型原生支持，减少 prompt 长度。

#### Conversation Turn Prompt (~2500 tokens)

```
行业角色设定 (1行)
decision_contract 复用 (~800 tokens)  ← 与 scene_recognizer 大量重复
诊断信息规则 (~200 tokens)
工具使用指导 (~150 tokens)
已采集事实列表 (~500 tokens)  ← 随对话增长
最近对话历史 (~800 tokens)  ← 截取最近20条
```

**问题**: `_decision_contract` 函数同时在 `recognize_scene` 和 `conversation_turn` 中使用，约 800 tokens 的规则内容每次都要传输。这 800 tokens 占每次 conversation_turn 调用的 ~30%。

### 3.3 Token 消耗估算

| 调用类型 | 次数 | 单次估计 Input | 单次估计 Output | 小计 Input |
|----------|------|---------------|----------------|------------|
| scene_recognize | 2 | ~1,500 | ~200 | ~3,000 |
| conversation_turn (Tool) | 20 | ~3,500 | ~150 | ~70,000 |
| conversation_turn (Final JSON) | 20 | ~3,800 | ~350 | ~76,000 |
| generate_report | 1 | ~4,000 | ~1,500 | ~4,000 |
| **总计** | **63** | - | - | **~153,000** |

> 注: Tool request/response 已合并计入 conversation_turn (Tool)，每轮可能产生 0-4 次 tool 交互。

---

## 四、Prompt 优化建议

### 4.1 🔴 高优先级

#### 建议1: 拆分 decision_contract，消除重复传输

**现状**: `_decision_contract()` 生成的 800+ token 规则在每轮 `conversation_turn` 中都完整传输。

**优化方案**:
```python
# 将不变的系统规则与动态状态分离
STATIC_ROUTING_RULES = """..."""  # 缓存在 SystemMessage 或模型 context

# 每轮只传输变化的部分
dynamic_context = {
    "scene": scene,           # ~50 tokens
    "existing_facts": facts,  # ~200 tokens (限制最近15条)
    "recent_messages": msgs,  # ~300 tokens (限制最近8条)
}
```

**预期效果**: 每轮节省 ~500 tokens，22轮 × 500 = **~11,000 tokens 节省**

#### 建议2: 使用 JSON Mode + Structured Output 替代 Prompt 内嵌 Schema

**现状**: JSON Schema 和枚举值全部写在 System Prompt 中（~400 tokens）。

**优化方案**:
```python
# 使用 DeepSeek 的 response_format + 简化 prompt
self.json_llm = ChatOpenAI(
    model=settings.llm_model,
    model_kwargs={
        "response_format": {"type": "json_object"},
        # DeepSeek 支持 JSON Schema 约束
        "json_schema": ConversationTurnOutput.model_json_schema(),
    },
)
```

**预期效果**: 减少 ~300 tokens/轮，且降低 JSON 解析失败率。

#### 建议3: 事实去重——在 Prompt 中增加显式去重指令

**现状**:
```
【已收集的运营事实】
- 桉树5年轮伐
- ...(40条)
```
模型在 40 条已有事实面前，仍然输出重复事实。

**优化方案**:
```markdown
【已收集的运营事实（共{count}条，请勿重复提取）】
{existing_text}

注意：以下事实已被记录，不要将其作为 new_facts 输出：
- 如果用户新消息中没有提供**实质性新信息**，new_facts 为空数组
- 对已有事实的**确认、复述、换个说法**不算新事实
```

**预期效果**: 事实重复率降低 60%+。

### 4.2 🟡 中优先级

#### 建议4: 动态调整完备度阈值展示逻辑

**现状**: 完备度 ≥80% 时在回复末尾展示「信息已比较充分」，但从第7轮到第22轮连续15轮展示此提示，造成用户疲劳。

**优化方案**:
```python
# 首次达到阈值时展示一次，之后不再重复
if completeness.score >= settings.complete_threshold:
    if not state.get("_threshold_prompt_shown"):
        reply += "\n\n**[信息已比较充分，点击按钮即可生成诊断报告]**"
        state["_threshold_prompt_shown"] = True
```

**预期效果**: 改善用户体验，避免重复提示。

#### 建议5: 增强工具调用触发率

**现状**: 22轮对话中工具检索调用较少，多数回答依赖模型记忆。

**优化方案**:
```markdown
【工具使用规则】
以下场景**必须**先检索再回答：
1. 涉及行业标准、基准数据、市场价格区间 → search_knowledge_base
2. 涉及最新政策、市场变化、新闻事件 → search_web
3. 涉及具体操作流程、案例参考 → search_knowledge_base
4. 涉及病虫害防治、技术方案等专业建议 → search_knowledge_base
5. 仅当用户纯粹闲聊、确认已知信息、或表达情绪时可不检索

检索到的资料是你的**可信参考来源**，引用时标注 [资料 N]。
```

**预期效果**: 知识库利用率提升，回答的专业性和可追溯性增强。

#### 建议6: 限制每轮 `existing_facts` 的上下文窗口

**现状**: 40 条事实全部传入每轮 prompt，占用 ~500 tokens 且信息密度下降。

**优化方案**:
```python
# 只传最近15条 + 按重要性采样的关键事实
recent_facts = existing_facts[-15:]
key_facts = [f for f in existing_facts if _is_key_fact(f)]
combined = recent_facts + key_facts[:5]
```

**预期效果**: 节省 ~200 tokens/轮，且减少信息过载。

### 4.3 🟢 低优先级

#### 建议7: Greeting Guide Prompt 优化

**现状**: Greeting guide 的 System Prompt 过于简短（3句话），缺少用户角色和对话目标引导。

**优化方案**:
```markdown
你是 BizSage 运营诊断助手，面向中小经营者提供免费、友好的初步诊断。

当前用户刚刚开始对话，尚未明确业务类型。请：
1. 用1-2句话打招呼，介绍你擅长的诊断方向（成本、销售、运营效率、转型策略）
2. 用一个开放性问题引导用户描述他的业务
3. 语气热情但不浮夸，像初次见面的顾问
```

#### 建议8: 报告生成的证据引用率提升

**现状**: 诊断报告中未出现 `[证据 N]` 引用标记，说明知识库检索结果未被有效利用。

**优化方案**: 在 generate_report prompt 中增加「输出前自查清单」：
```markdown
输出报告前请自查：
- [ ] 是否在有行业标准的论断后标注了 [证据 N]？
- [ ] 是否所有 [证据 N] 编号与提供的证据列表一致？
- [ ] 是否区分了「事实陈述」与「专家推断」？
```

---

## 五、对话完整记录（摘要）

| 轮次 | 用户（LLM模拟经营者） | BizSage 助手 | 阶段 |
|------|----------------------|-------------|------|
| 1 | 你好，我是做林业的，在南方有一片林场 | 询问面积和树种 | scene_recognize → conversation_turn |
| 2 | 5000亩，种桉树，5年轮伐，第3年 | 询问管护成本 | conversation_turn |
| 3 | 年成本250万，人工和肥料涨 | 询问产量和销售渠道 | conversation_turn |
| 4 | 亩产6-7吨，收购价跌到500多 | 询问机械化意愿 | conversation_turn |
| 5 | 机械想过但山路难走 | 询问林地所有权 | conversation_turn |
| 6 | 自有林地不用租金 | 询问地形坡度 | conversation_turn |
| 7 | 丘陵，七八成能走车 | 推荐小型履带机 | conversation_turn |
| 8 | 最陡30度，小型履带靠谱吗 | 确认机型+询问用工缺口 | conversation_turn |
| 9 | 需30人，临时工只能招一半 | 询问利润率 | conversation_turn |
| 10 | 利润率20-25%，担心市场波动 | 建议拓宽销售渠道 | conversation_turn |
| 11 | 想过加工但投入大 | 给多渠道建议+问运输距离 | conversation_turn |
| 12 | 到主干道20公里，分级有搞头吗 | 分析分级经济性+问采伐机预算 | conversation_turn |
| 13 | 怎么找到按等级收的买家 | 给买家寻找渠道+问径级分布 | conversation_turn |
| 14 | 大径材占四成，愿意试分级 | 确认+转向病虫害话题 | conversation_turn |
| 15 | 白蚁青枯病，年农药5-6万 | 介绍平台操作+问采伐机预算 | conversation_turn |
| 16 | 二手十几二十万能接受 | 转向补贴政策话题 | conversation_turn |
| 17 | 补贴怎么申请 | 详解农机补贴流程+问转型意愿 | conversation_turn |
| 18 | 松树 vs 林下经济哪个靠谱 | 分析两种路径+问现金流偏好 | conversation_turn |
| 19 | 短期现金流，怕技术门槛 | 推荐养蜂+问培训渠道 | conversation_turn |
| 20 | 每年多赚三四十万就松口气 | 问养蜂投入预算 | conversation_turn |
| 21 | 百来箱三五万，先试水 | 确认试水策略 | conversation_turn |
| 22 | 白蚁会不会影响养蜂 | 建议先治白蚁 | conversation_turn |
| — | [请求生成报告] | 完整诊断报告(3410字) | generate_report |

---

## 六、结论

### 正面发现
1. **对话引擎设计合理**: LangGraph 的状态机路由（scene_recognize → conversation_turn → await_input → 循环）能有效处理多轮诊断对话
2. **行业知识丰富**: 模型对桉树林业有深入理解，能给出实操性建议（如小型履带机、分级销售、林下养蜂）
3. **用户体验良好**: 话术自然、emoji恰当、问题递进有逻辑

### 改进方向
1. **Prompt 效率**: 存在 ~40% 的冗余 token 消耗（重复的 decision_contract + 过长的 existing_facts）
2. **工具利用率**: 知识库检索触发不足，多数回答依赖模型记忆而非已审核的行业资料
3. **重复控制**: 事实采集存在约 15% 的重复率，完备度提示连续触发造成疲劳感

### 关键数据
- 22轮对话总 Token 消耗估算: **~153,000 input tokens**
- 优化后预期节省: **~30,000 tokens (约 20%)**
- 报告生成: 3,410 字，结构完整，覆盖7大维度
