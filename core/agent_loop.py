"""自主 Agent Loop（T1 核心大脑）：ReAct 规划-执行-观察循环。

让 LLM 用 tool_choice=auto 自主决定调工具，解析 tool_calls → 经 tools_registry 执行
→ 回填 messages → 循环，直到模型不再调用工具或达到最大轮数。
这是 MiniYuxi 从"检索问答壳"走向"真·AI Agent"的关键：模型自己决策，而非手写正则触发。

设计要点（守红线）：
- 离线(无 Key) / 网关失败时返回 None，由 rag.answer 退化为原单次 RAG，不影响 selftest 离线基线。
- 不新增 pip 依赖，复用 requests（已在隔离 venv）。
- T3 服务端记忆在 run() 入口注入 system；T4 规划通过 system 引导 + 自然多轮 tool call 体现。
"""
import json
from . import config, gateway, rag, tools_registry

MAX_LOOPS = 6


def _to_openai_tools() -> list:
    """把工具注册表转换为 OpenAI function calling 工具声明。"""
    tools = []
    for t in tools_registry.list_tools():
        params = t.get("schema") or {}
        if not isinstance(params, dict):
            params = {}
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": params,
            },
        })
    return tools


def run(system: str, user_prompt: str, history: list | None = None,
        tenant_id: str = None, memories: list | None = None) -> dict | None:
    """执行自主循环。返回 {answer, mode, model, tool_calls_used, loop_trace, memories_used}
    或 None（离线/网关失败，由 caller 退化）。"""
    if not config.llm_enabled():
        return None

    tools = _to_openai_tools()
    messages = []
    for h in (history or [])[-rag.MAX_HISTORY:]:
        role = h.get("role") if isinstance(h, dict) else None
        content = (h.get("content") if isinstance(h, dict) else "") or ""
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:rag.MAX_HISTORY_CHARS]})
    # 服务端长期记忆注入（T3）：作为一条 system 级的上下文消息放在用户提问前
    if memories:
        mem_text = "\n".join(f"- {m}" for m in memories[:8])
        messages.append({"role": "system", "content": "【长期记忆·历史对话摘要】\n" + mem_text})
    messages.append({"role": "user", "content": user_prompt})

    final_text = ""
    used_tools: list = []
    loop_trace: list = []
    last_assistant = ""

    for _ in range(MAX_LOOPS):
        res = gateway.chat_with_tools(system, messages, tools, tenant_id=tenant_id)
        if not res["ok"]:
            return None  # 网关失败（如限流）→ caller 退化
        msg_content = res["text"]
        tool_calls = res["tool_calls"]
        last_assistant = msg_content or last_assistant

        asst_msg = {"role": "assistant", "content": msg_content or ""}
        if tool_calls:
            asst_msg["tool_calls"] = [{
                "id": tc["id"], "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
            } for tc in tool_calls]
        messages.append(asst_msg)

        if not tool_calls:
            final_text = msg_content
            break

        for tc in tool_calls:
            name, args = tc["name"], (tc["arguments"] or {})
            r = tools_registry.call_tool(name, args, tenant_id=tenant_id)
            if "result" in r:
                out = str(r["result"])
            elif "content" in r:
                out = str(r["content"])
            elif "error" in r:
                out = "工具执行出错：" + str(r["error"])
            else:
                out = json.dumps(r, ensure_ascii=False)
            used_tools.append(name)
            loop_trace.append({"tool": name, "args": args, "result": out[:600]})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": out[:1600]})

    if not final_text:
        final_text = last_assistant or "（未能生成最终回答）"

    return {
        "answer": final_text,
        "mode": "agent",
        "model": config.LLM_MODEL,
        "tool_calls_used": used_tools,
        "loop_trace": loop_trace,
        "memories_used": bool(memories),
    }
