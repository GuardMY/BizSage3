#!/usr/bin/env python3
"""
BizSage3 对话测试脚本 — 双端实时生成版
- BizSage 助手侧: 通过 BizSage API 实时生成
- 用户侧: 通过 DeepSeek API 实时生成，模拟林业经营者
"""
import requests
import json
import sys
import time
from openai import OpenAI

BASE_URL = "http://localhost:3000/api/v1"
ADMIN_TOKEN = "replace-with-a-random-admin-token"

# 用户侧 LLM 配置（与 BizSage 后端共用 DeepSeek）
USER_LLM = OpenAI(
    api_key="sk-e92e59d2e9814e6c8a309fc9e84c7e0d",
    base_url="https://api.deepseek.com",
)

USER_MODEL = "deepseek-v4-flash"

# 用户角色设定
USER_SYSTEM_PROMPT = """你是一位南方的林业经营者（林场主），正在与 BizSage 运营诊断助手进行对话。

你的背景：
- 在南方某省拥有一片约5000亩的林场，主要种植桉树
- 桉树5年一个轮伐期，目前大部分是第3年的树
- 有20个固定工人，忙时请临时工（但越来越难找）
- 主要卖给木材加工厂，收购价最近两年在降
- 面临成本上涨、白蚁病虫害、环保合规等压力
- 在考虑林下经济（养鸡/菌菇）、深加工、碳汇交易等多元化方向
- 对数字化管理有兴趣但不太懂

你的行为准则：
1. 像真实的经营者一样自然对话，用口语化表达
2. 每次只回复1-3句话（30-80字），像真实聊天，不要长篇大论
3. 根据助手的问题和引导来回答，逐步透露更多经营信息
4. 偶尔表示困惑、追问细节或表示认同
5. 不要一次性把所有信息都说完，像正常对话一样逐步展开
6. 适当提出自己的疑问和顾虑
7. 不要主动终结对话，让对话自然延续

注意：你的回复应该是纯文本，直接作为用户消息发送，不要加任何前缀标签。"""

SESSION_COOKIE = None


def login():
    global SESSION_COOKIE
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"token": ADMIN_TOKEN},
    )
    if resp.status_code == 200:
        SESSION_COOKIE = resp.cookies.get("bizsage_session")
        print(f"✅ 登录成功: {resp.json()['role']}")
        return True
    print(f"❌ 登录失败: {resp.status_code} {resp.text}")
    return False


def create_session():
    resp = requests.post(
        f"{BASE_URL}/sessions",
        cookies={"bizsage_session": SESSION_COOKIE},
    )
    if resp.status_code == 201:
        data = resp.json()
        print(f"✅ 会话创建成功: {data['id'][:16]}...")
        return data["id"]
    print(f"❌ 创建会话失败: {resp.status_code} {resp.text}")
    return None


def send_message(session_id, content, msg_num):
    """发送消息到 BizSage 并处理 SSE 流，返回助手的完整回复"""
    payload = {
        "content": content,
        "client_message_id": f"test-msg-{msg_num}-{int(time.time() * 1000)}",
    }

    print(f"\n{'─'*55}")
    print(f"📤 [第{msg_num}轮-用户]: {content}")

    try:
        resp = requests.post(
            f"{BASE_URL}/sessions/{session_id}/messages",
            json=payload,
            cookies={"bizsage_session": SESSION_COOKIE},
            stream=True,
            timeout=180,
        )

        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}")
            body = ""
            for line in resp.iter_lines():
                if line:
                    body += line.decode('utf-8', errors='replace')[:500]
            print(f"  响应: {body[:300]}")
            return None

        assistant_reply = ""
        stage_info = ""
        suggested_replies = []
        current_event = ""

        for line in resp.iter_lines():
            if not line:
                continue
            line_text = line.decode('utf-8', errors='replace')

            if line_text.startswith("event: "):
                current_event = line_text[7:].strip()
            elif line_text.startswith("data: "):
                try:
                    data = json.loads(line_text[6:])

                    if current_event == "stage":
                        stage_info = data.get("label", data.get("stage", ""))
                        print(f"  🔄 [{stage_info}]")
                    elif current_event == "assistant.message":
                        assistant_reply = data.get("content", "")
                        # 截断显示
                        display = assistant_reply[:200] + ("..." if len(assistant_reply) > 200 else "")
                        print(f"  📥 [BizSage]: {display}")
                    elif current_event == "suggested_replies":
                        suggested_replies = data.get("replies", [])
                        if suggested_replies:
                            print(f"  💡 [建议回复]: {suggested_replies}")
                    elif current_event == "error":
                        print(f"  ❌ [错误]: {data.get('message', '')}")
                except json.JSONDecodeError:
                    pass

        return {
            "reply": assistant_reply,
            "stage": stage_info,
            "suggested_replies": suggested_replies,
        }
    except requests.exceptions.Timeout:
        print(f"  ⏰ 请求超时")
        return None
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return None


def generate_user_message(history_text, round_num):
    """使用 DeepSeek 生成下一条用户消息"""
    user_prompt = f"""以下是迄今为止的对话历史：

{history_text}

请作为林业经营者，生成你的下一条回复（第{round_num}轮）。
记住：
- 1-3句话即可，30-80字
- 自然回应助手刚才说的话
- 可以补充新的经营信息、提问或表达顾虑
- 不要重复已经详细讨论过的内容
- 像真实对话一样自然推进"""

    try:
        resp = USER_LLM.chat.completions.create(
            model=USER_MODEL,
            messages=[
                {"role": "system", "content": USER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=200,
        )
        content = resp.choices[0].message.content.strip()
        # 清理可能的引号包裹
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        if content.startswith('「') and content.endswith('」'):
            content = content[1:-1]
        return content
    except Exception as e:
        print(f"  ⚠️ 用户消息生成失败: {e}")
        return None


def get_report(session_id):
    """获取最新报告"""
    resp = requests.get(
        f"{BASE_URL}/sessions/{session_id}/reports",
        cookies={"bizsage_session": SESSION_COOKIE},
    )
    if resp.status_code == 200:
        reports = resp.json()
        if reports:
            report_id = reports[0]["id"]
            resp2 = requests.get(
                f"{BASE_URL}/sessions/{session_id}/reports/{report_id}",
                cookies={"bizsage_session": SESSION_COOKIE},
            )
            if resp2.status_code == 200:
                return resp2.json()
    return None


def main():
    print("🚀 BizSage3 双端实时对话测试")
    print("=" * 55)

    if not login():
        sys.exit(1)

    session_id = create_session()
    if not session_id:
        sys.exit(1)

    # 构建对话历史文本
    conversation_history = []

    # 初始用户消息（种子消息，手动设置以启动对话）
    initial_message = "你好，我是做林业的，在南方有一片林场，想请你帮我做一下经营诊断"

    results = []
    total_rounds = 22  # 目标轮数

    for round_num in range(1, total_rounds + 1):
        if round_num == 1:
            user_msg = initial_message
        else:
            # 根据对话历史实时生成用户消息
            history_text = "\n".join(conversation_history[-10:])  # 最近10轮
            user_msg = generate_user_message(history_text, round_num)
            if user_msg is None:
                print("⚠️ 无法生成用户消息，使用fallback...")
                user_msg = "嗯，你说得有道理。还有什么其他方面需要注意的吗？"
            time.sleep(1)  # 用户思考间隔

        # 发送到 BizSage
        result = send_message(session_id, user_msg, round_num)

        if result and result["reply"]:
            assistant_reply = result["reply"]
            # 更新对话历史
            conversation_history.append(f"经营者: {user_msg}")
            conversation_history.append(f"BizSage: {assistant_reply[:200]}")

            results.append({
                "round": round_num,
                "user_message": user_msg,
                "assistant_reply": assistant_reply,
                "assistant_reply_short": assistant_reply[:200],
                "stage": result["stage"],
                "suggested_replies": result["suggested_replies"],
            })

            print(f"  ✅ 第{round_num}轮完成 (助手回复{len(assistant_reply)}字)")
        else:
            print(f"  ⚠️ 第{round_num}轮失败，跳过")
            results.append({
                "round": round_num,
                "user_message": user_msg,
                "assistant_reply": "ERROR: 无响应",
                "stage": "error",
            })
            # 失败时也要更新历史
            conversation_history.append(f"经营者: {user_msg}")
            conversation_history.append(f"BizSage: [无响应]")

        time.sleep(0.5)

    # 请求生成诊断报告
    print(f"\n{'='*55}")
    print("📊 触发诊断报告生成...")

    resp = requests.post(
        f"{BASE_URL}/sessions/{session_id}/reports",
        cookies={"bizsage_session": SESSION_COOKIE},
    )

    if resp.status_code == 202:
        print("✅ 报告生成请求已提交（202）")
        for attempt in range(30):
            time.sleep(3)
            report = get_report(session_id)
            if report and report.get("status") == "completed":
                markdown = report.get("markdown", "")
                print(f"✅ 报告生成完成！({len(markdown)} 字)")
                results.append({
                    "round": total_rounds + 1,
                    "user_message": "[请求生成诊断报告]",
                    "assistant_reply": markdown,
                    "stage": "report_generated",
                    "is_report": True,
                })
                break
            print(f"  ⏳ 等待中... (尝试 {attempt+1}/30)")
    else:
        print(f"⚠️ 报告请求失败: {resp.status_code} {resp.text[:200]}")

    # 保存完整对话结果
    output_file = "/root/project/BizSage3/scripts/conversation_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "session_id": session_id,
            "total_rounds": len(results),
            "user_role": "南方林业经营者(LLM模拟)",
            "conversations": results,
            "full_transcript": "\n\n---\n\n".join(conversation_history),
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*55}")
    print(f"✅ 测试完成！共 {len(results)} 轮")
    print(f"📁 对话结果: {output_file}")
    print(f"📋 Session ID: {session_id}")
    print(f"\n⚠️ 请勿关闭，等待收集日志...")


if __name__ == "__main__":
    main()
