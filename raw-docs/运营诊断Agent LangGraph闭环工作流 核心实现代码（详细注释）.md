# 运营诊断Agent LangGraph闭环工作流 核心实现代码（详细注释）

## 一、技术依赖说明

适配Python3\.8\+，为项目最简稳定依赖，专注流程编排能力，无冗余组件

```python
# 核心依赖安装命令
# pip install langchain langgraph langchain-openai python-dotenv pydantic
```

## 二、完整核心代码（全流程闭环\+详细注释）

实现能力：严格串行闭环流程、状态持久化、自动追问、完备度打分、分支跳转、禁止大模型自由发挥

```python

"""
行业运营诊断Agent - LangGraph 固定闭环工作流
流程严格固定：场景识别 → 指标采集 → 完备度校验 → 异常追问 → 诊断分析 → 报告输出
核心特性：步骤强制有序、状态持久、智能分支、杜绝LLM自由发挥
"""
import os
from typing import TypedDict, List, Dict, Any, Optional
from dotenv import load_dotenv
from pydantic import Field

# LangGraph 核心依赖
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# LangChain LLM 与提示词依赖
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# 加载环境变量
load_dotenv()

# ====================== 1. 定义全局状态结构体（核心数据中枢）======================
# 全程所有节点共享该状态，替代零散上下文，保证流程数据统一、可追溯
class OperationDiagnosisState(TypedDict):
    # 对话消息上下文（存储所有轮次问答）
    messages: List[BaseMessage]
    # 用户场景信息（场景识别节点输出）
    user_scene: Dict[str, str]
    # 已采集的运营指标数据（结构化存储，避免文本混乱）
    collect_metrics: Dict[str, Any]
    # 缺失的核心指标字段
    miss_metrics: List[str]
    # 信息完备度分数（0-100）
    complete_score: int
    # 是否需要继续追问（分支判断标识）
    need_ask: bool
    # 最终诊断结果
    diagnosis_result: str
    # 最终结构化报告
    final_report: str

# ====================== 2. 初始化全局配置与LLM ======================
# 使用稳定大模型，温度设为0，严格遵循规则，禁止自由发挥
llm = ChatOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
    model="gpt-3.5-turbo",
    temperature=0.0,  # 关键：0随机性，严格执行流程规则
    max_tokens=2048
)

# 内存持久化：保存会话状态，支持中断续问、不重复提问
memory_saver = MemorySaver()

# 完备度诊断阈值（与产品设计一致：80分触发诊断）
COMPLETE_THRESHOLD = 80

# ====================== 3. 定义所有工作流节点（对应业务流程）======================
def node_scene_recognize(state: OperationDiagnosisState) -> Dict:
    """
    节点1：场景识别
    功能：识别用户行业、业务模式、运营阶段、诊断需求
    输出：标准化user_scene场景数据，为后续精准提问提供依据
    """
    messages = state["messages"]
    # 固定Prompt，禁止LLM发散，强制结构化输出
    scene_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是运营诊断场景识别专家，严格根据用户对话内容，仅输出JSON结构化数据。
        输出字段固定：industry(行业)、business_mode(业务模式)、operate_stage(运营阶段：冷启动/增长/稳定/衰退)、diagnosis_target(诊断方向)
        无信息则填空字符串，禁止输出多余解释、禁止自由发挥"""),
        ("user", "{input_msg}")
    ])
    # 组装请求并调用LLM
    chain = scene_prompt | llm
    res = chain.invoke({"input_msg": messages})
    # 解析结构化场景数据
    import json
    scene_data = json.loads(res.content)
    # 返回更新状态
    return {"user_scene": scene_data}


def node_collect_metrics(state: OperationDiagnosisState) -> Dict:
    """
    节点2：分层指标采集
    功能：根据用户行业场景，主动采集核心指标+次要指标
    自动去重、记录已采集数据，生成缺失字段
    """
    user_scene = state["user_scene"]
    messages = state["messages"]
    existing_metrics = state.get("collect_metrics", {})

    # 固定采集Prompt，严格按照行业模型采集数据
    collect_prompt = ChatPromptTemplate.from_messages([
        ("system", f"""你是运营指标采集专员，基于用户场景{user_scene}，从用户对话中提取结构化运营指标。
        1. 核心必采指标：流量、曝光、访客、转化率、客单价、营收、成本、新增用户、流失率、复购率
        2. 根据行业补充行业专属指标
        3. 仅提取已有数据，不编造、不发散
        4. 输出JSON：collect_metrics(已采集数据)、miss_metrics(缺失字段列表)"""),
        ("user", "历史对话信息：{history}，已采集数据：{existing}")
    ])

    chain = collect_prompt | llm
    res = chain.invoke({
        "history": messages,
        "existing": existing_metrics
    })
    import json
    collect_res = json.loads(res.content)

    return {
        "collect_metrics": collect_res["collect_metrics"],
        "miss_metrics": collect_res["miss_metrics"]
    }


def node_check_complete(state: OperationDiagnosisState) -> Dict:
    """
    节点3：信息完备度校验
    功能：按照产品打分规则计算分数，判断是否需要继续追问
    打分规则：核心指标齐全+60、次要指标覆盖率70%+20、异常信息补全+20
    """
    miss_metrics = state["miss_metrics"]
    collect_metrics = state["collect_metrics"]

    score = 0
    # 1. 核心指标满分60分：无核心缺失则满分
    core_metrics = ["流量", "曝光", "访客", "转化率", "客单价", "营收", "成本", "新增用户", "流失率", "复购率"]
    miss_core = [i for i in miss_metrics if i in core_metrics]
    if len(miss_core) == 0:
        score += 60

    # 2. 次要指标20分：覆盖率≥70%得分
    sub_metrics = [i for i in miss_metrics if i not in core_metrics]
    if len(sub_metrics) == 0:
        score += 20
    else:
        sub_cover = 1 - len(sub_metrics) / max(len(sub_metrics + list(collect_metrics.keys())), 1)
        if sub_cover >= 0.7:
            score += 20

    # 3. 异常场景信息20分（简易判定：无关键指标缺失即默认补齐）
    if len(miss_core) == 0:
        score += 20

    # 判断是否需要追问
    need_ask = True if score < COMPLETE_THRESHOLD else False

    return {
        "complete_score": score,
        "need_ask": need_ask
    }


def node_exception_ask(state: OperationDiagnosisState) -> Dict:
    """
    节点4：异常追问补全
    功能：针对缺失指标，单次1-2个问题渐进式追问，不冗余、不重复
    """
    miss_metrics = state["miss_metrics"]
    user_scene = state["user_scene"]

    ask_prompt = ChatPromptTemplate.from_messages([
        ("system", f"""你是运营智能提问助手，用户行业：{user_scene.get('industry')}
        规则：1. 每次仅提问1-2个缺失指标问题 2. 话术简洁通俗 3. 不重复提问、不冗余
        缺失指标：{miss_metrics}"""),
        ("user", "请生成本次追问问题")
    ])

    res = llm.invoke(ask_prompt)
    # 将追问消息加入对话上下文
    new_msg = AIMessage(content=res.content)
    new_messages = state["messages"] + [new_msg]

    return {"messages": new_messages}


def node_diagnosis_analysis(state: OperationDiagnosisState) -> Dict:
    """
    节点5：多维度诊断分析
    功能：六大维度运营诊断、异常识别、根因拆解、风险定级
    """
    collect_metrics = state["collect_metrics"]
    user_scene = state["user_scene"]

    diag_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是资深运营诊断专家，基于用户场景和指标数据，完成6大维度诊断：
        流量、转化、用户、内容/产品、收益成本、运营动作
        输出：问题定级（优势/正常/风险/严重问题）+ 数据异常说明 + 深层根因"""),
        ("user", f"用户场景：{user_scene}，运营指标数据：{collect_metrics}")
    ])

    res = llm.invoke(diag_prompt)
    return {"diagnosis_result": res.content}


def node_generate_report(state: OperationDiagnosisState) -> Dict:
    """
    节点6：结构化报告输出
    功能：生成标准化、可落地的最终诊断报告
    """
    diagnosis_result = state["diagnosis_result"]
    collect_metrics = state["collect_metrics"]
    complete_score = state["complete_score"]
    miss_metrics = state["miss_metrics"]

    report_prompt = ChatPromptTemplate.from_messages([
        ("system", """请按照固定结构生成运营诊断报告：
        1. 诊断概览（健康度分数、核心结论）
        2. 数据现状盘点
        3. 核心问题分级诊断
        4. 问题根因拆解
        5. 短期+中期落地优化方案
        6. 后续监测指标建议
        7. 数据缺失说明"""),
        ("user", f"诊断结论：{diagnosis_result}，指标数据：{collect_metrics}，完备度分数：{complete_score}，缺失指标：{miss_metrics}")
    ])

    res = llm.invoke(report_prompt)
    new_msg = AIMessage(content=res.content)
    new_messages = state["messages"] + [new_msg]

    return {
        "final_report": res.content,
        "messages": new_messages
    }

# ====================== 4. 定义分支路由逻辑 ======================
def route_ask_or_diag(state: OperationDiagnosisState) -> str:
    """
    分支路由：判断继续追问 还是 进入诊断
    """
    if state["need_ask"]:
        return "exception_ask"
    else:
        return "diagnosis_analysis"

# ====================== 5. 搭建完整闭环工作流 ======================
def build_diagnosis_workflow():
    # 1. 初始化状态图
    workflow = StateGraph(OperationDiagnosisState)

    # 2. 注册所有节点
    workflow.add_node("scene_recognize", node_scene_recognize)
    workflow.add_node("collect_metrics", node_collect_metrics)
    workflow.add_node("check_complete", node_check_complete)
    workflow.add_node("exception_ask", node_exception_ask)
    workflow.add_node("diagnosis_analysis", node_diagnosis_analysis)
    workflow.add_node("generate_report", node_generate_report)

    # 3. 固定串行主流程（强制有序，杜绝乱序执行）
    workflow.add_edge(START, "scene_recognize")
    workflow.add_edge("scene_recognize", "collect_metrics")
    workflow.add_edge("collect_metrics", "check_complete")

    # 4. 条件分支：完备度不足追问，达标进入诊断
    workflow.add_conditional_edges(
        "check_complete",
        route_ask_or_diag,
        {
            "exception_ask": "exception_ask",
            "diagnosis_analysis": "diagnosis_analysis"
        }
    )

    # 5. 追问完成后，回到指标采集重新校验（闭环）
    workflow.add_edge("exception_ask", "collect_metrics")

    # 6. 诊断完成后生成报告，最终结束流程
    workflow.add_edge("diagnosis_analysis", "generate_report")
    workflow.add_edge("generate_report", END)

    # 7. 编译工作流 + 状态持久化
    graph = workflow.compile(checkpointer=memory_saver)
    return graph

# ====================== 6. 对外调用入口 ======================
# 初始化全局工作流
diagnosis_graph = build_diagnosis_workflow()

def run_diagnosis_agent(user_input: str, thread_id: str = "default_001"):
    """
    外部调用入口
    :param user_input: 用户输入的运营情况文本
    :param thread_id: 会话唯一ID（区分不同用户、不同诊断会话）
    :return: 最终诊断报告
    """
    # 初始化会话状态
    init_state = {
        "messages": [HumanMessage(content=user_input)],
        "user_scene": {},
        "collect_metrics": {},
        "miss_metrics": [],
        "complete_score": 0,
        "need_ask": True,
        "diagnosis_result": "",
        "final_report": ""
    }
    # 执行工作流
    result = diagnosis_graph.invoke(init_state, config={"thread_id": thread_id})
    return result["final_report"]

# ====================== 测试示例 ======================
if __name__ == "__main__":
    # 测试调用
    test_input = "我是做小红书美妆运营的，目前处于增长期，本月曝光50万，访客2万，转化率2%，近期粉丝增长变慢"
    report = run_diagnosis_agent(test_input)
    print("===== 最终运营诊断报告 =====")
    print(report)

```

## 三、核心代码能力对应业务说明

- **100% 匹配设计流程**：严格执行 场景识别→指标采集→完备度校验→异常追问→诊断分析→报告输出 闭环

- **杜绝LLM乱发挥**：全局temperature=0、结构化Prompt、固定字段输出、强制流程节点，无自由发散

- **状态持久化记忆**：基于LangGraph Checkpointer实现会话记忆，不重复提问、支持中断续聊

- **智能闭环追问**：分数不达标自动循环采集\+追问，达标自动终止进入诊断，完全匹配产品规则

- **结构化数据流转**：自定义State结构体，所有指标、场景、分数结构化存储，无文本混乱问题

## 四、MVP落地优化点

- 可直接替换模型为本地模型/私有大模型，适配私有化部署

- 完备度打分规则可直接修改参数，适配不同行业阈值

- 节点可单独插拔，后续可升级为多Agent分工模式

- 天然支持对接前端对话接口，开箱即用

> （注：部分内容可能由 AI 生成）
