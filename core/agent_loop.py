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
from . import config, gateway, provider_router, rag, tools_registry

# ReAct 反思轮数上限：2026-09-30 起由 core/config.py 统一管理（环境变量
# MINIYUXI_AGENT_MAX_LOOPS），不再是硬编码。config 在 import 期读取环境变量，
# 测试可用 importlib.reload(config) 覆盖。
MAX_LOOPS = int(getattr(config, "AGENT_MAX_LOOPS", 6) or 6)


def _llm_chat(system, messages, tools, tenant_id=None, provider=None, model=None):
    """Agent Loop 的 LLM 出口：走 provider_router 以获得多供应商故障转移。

    为什么不再直连 gateway：gateway 只有单一 config 单例，供应商 429/5xx/超时后
    直接返回 offline，Agent 在生产上会毫无征兆地退化。provider_router 提供
    「出境闸门 → 瞬断重试 → 按优先级切下一个供应商 → 离线兜底」的完整链路，
    对应 OpenClaw §4.3 failover 语义。

    兼容性：provider_router.chat_with_tools 的返回结构与 gateway.chat_with_tools
    一致（ok/text/tool_calls/err/usage），调用方无需改动。
    """
    return provider_router.chat_with_tools(
        system, messages, tools,
        provider_id=provider, model=model, tenant_id=tenant_id,
    )


def _to_openai_tools(allowed_toolsets=None) -> list:
    """把工具注册表转换为 OpenAI function calling 工具声明。

    allowed_toolsets: None（默认）全量暴露，向后兼容；否则仅暴露 toolset
    落在允许集合内的工具（Hermes 三·按 toolset 过滤：不同入口/租户只给必要能力，
    既降风险也省上下文体积）。"""
    tools = []
    for t in tools_registry.list_tools():
        if allowed_toolsets is not None and t.get("toolset") not in allowed_toolsets:
            continue
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


def _emit(emit, etype: str, payload: dict) -> None:
    """旁路观测：emit 事件给调用方（如 SSE 流）。**绝不影响主链路**。"""
    if emit is None:
        return
    try:
        emit({"type": etype, "payload": payload})
    except Exception:
        pass


# 粗粒度成本估算单价（单位：元 / 千 token）。网关未回传真实 cost 时兜底，
# 目的是让 BudgetGuard.max_cost 闸门**真的能触发**，而非追求精确计费。
# 精确账单以 core/usage.py 记录为准。
_COST_PER_1K = {
    "deepseek": (0.002, 0.008),
    "doubao": (0.0008, 0.002),
    "qwen": (0.002, 0.006),
    "gpt": (0.015, 0.060),
    "claude": (0.022, 0.110),
}
_DEFAULT_PRICE = (0.005, 0.020)


def _estimate_cost(prompt_tokens: int, completion_tokens: int, model: str | None = None) -> float:
    """按 token 数估算一次 LLM 调用成本（元）。估算失败返回 0.0，绝不影响主链路。"""
    try:
        name = (model or config.LLM_MODEL or "").lower()
        pin, pout = _DEFAULT_PRICE
        for key, prices in _COST_PER_1K.items():
            if key in name:
                pin, pout = prices
                break
        return round((prompt_tokens / 1000.0) * pin + (completion_tokens / 1000.0) * pout, 8)
    except Exception:
        return 0.0


def run(system: str, user_prompt: str, history: list | None = None,
        tenant_id: str = None, memories: list | None = None, trace_id: str = None,
        provider: str | None = None, model: str | None = None, emit=None,
        allowed_toolsets: list | None = None,
        cancel_check=None) -> dict | None:
    """执行自主循环。返回 {answer, mode, model, tool_calls_used, loop_trace, memories_used, trace_id}
    或 None（离线/网关失败，由 caller 退化）。

    企业级增强（对齐 docs/enterprise-boundary-desktop-web-20260929.md）：
    - ④ 可观测性：每次 LLM 调用 / 工具执行都挂 trace_id 结构化 span（observability）。
    - ⑤ 成本硬熔断：每步过 BudgetGuard（步数/超时/token/成本/租户预算/失控循环），熔断即终止并告警 SOC。

    2026-09-30 加固（对应 docs/OpenClaw_Agent调度机制五阶段技术文档 §5.5）：
    - allowed_toolsets：按 toolset 过滤暴露给模型的工具（多租户最小权限，默认 None=全量向后兼容）。
    - cancel_check：可调用对象，返回 True 表示请求取消；每轮循环前检查，实现协作式中断。
    - 审批卡识别：工具返回 status=="pending" 时**不再当普通结果喂回模型**，
      改为回灌一条明确的「待人工审批」观察并终止本轮循环，避免模型误判已执行完。
    """
    if not config.llm_enabled():
        return None

    # 多租户闸门（2026-09-30 接入）：此前 multitenant.enforce 全仓零调用，
    # 配额闸门形同虚设。这里在入口做一次强制校验，拒绝时直接返回，
    # 不产生任何 token 消耗，并写 SOC 链留痕。
    if tenant_id:
        try:
            from . import multitenant
            gate = multitenant.enforce(tenant_id, "agent_run")
            if not gate.get("allow"):
                _emit(emit, "lifecycle", {"phase": "blocked", "reason": gate.get("reason")})
                return {
                    "answer": "（已被多租户配额闸门拦截：%s）" % gate.get("reason"),
                    "mode": "blocked", "model": model or config.LLM_MODEL,
                    "tool_calls_used": [], "loop_trace": [],
                    "memories_used": False, "trace_id": None,
                    "blocked": True, "block_reason": gate.get("reason"),
                }
        except Exception:
            # 闸门自身异常不得阻断主链路（fail-open，与 egress 策略一致由部署侧决定）
            pass

    from . import observability, circuit_breaker, soc_audit
    tid = observability.start_trace(trace_id)
    guard = circuit_breaker.BudgetGuard(tenant_id=tenant_id)
    _emit(emit, "lifecycle", {"phase": "start", "trace_id": tid})

    tools = _to_openai_tools(allowed_toolsets)
    messages = []
    from . import memory_slim
    for h in memory_slim.slim_messages(history):
        role = h.get("role") if isinstance(h, dict) else None
        content = (h.get("content") if isinstance(h, dict) else "") or ""
        if (role in ("user", "assistant") or (content or "").startswith(memory_slim.SLIM_PREFIX)) and content:
            messages.append({"role": role, "content": content[:rag.MAX_HISTORY_CHARS]})
    # 用户提问（本轮主体）
    user_msg = user_prompt
    # 服务端长期记忆注入（T3）：Hermes 四·临时/可变上下文应注入 user message 段，
    # 而非塞进 system prompt——避免冲刷稳定前缀、破坏 prompt cache，并杜绝双 system 隐患。
    if memories:
        mem_text = "\n".join(f"- {m}" for m in memories[:8])
        user_msg = (user_prompt + "\n\n【长期记忆·历史对话摘要】\n" + mem_text)
    messages.append({"role": "user", "content": user_msg})

    final_text = ""
    used_tools: list = []
    loop_trace: list = []
    last_assistant = ""
    circuit_open = False
    circuit_reason = None
    # 审批挂起单：命中审批门时填充。无工具调用路径下必须已初始化，
    # 否则末尾 if pending_approval 会抛 UnboundLocalError。
    pending_approval = None

    for _ in range(MAX_LOOPS):
        # 协作式中断：调用方（agent_runtime.AgentSession.cancel）置位后在此生效。
        # 同步 loop 无法强制杀线程，只能在每个工具边界安全退出。
        if cancel_check is not None:
            try:
                if cancel_check():
                    _emit(emit, "lifecycle", {"phase": "cancelled", "trace_id": tid})
                    return {
                        "answer": "（已取消）", "mode": "agent",
                        "model": model or config.LLM_MODEL, "tool_calls_used": used_tools,
                        "loop_trace": loop_trace, "memories_used": bool(memories),
                        "trace_id": tid, "cancelled": True,
                    }
            except Exception:
                pass
        # 步级熔断检查（步数 / 超时 / token / 成本 / 租户预算）
        decision, reason = guard.check_step()
        if decision == "open":
            circuit_open, circuit_reason = True, reason
            break
        with observability.span("llm", kind="llm", tenant_id=tenant_id) as lsp:
            res = _llm_chat(system, messages, tools, tenant_id=tenant_id,
                            provider=provider, model=model)
        if not res["ok"]:
            lsp.set_status("offline")
            _emit(emit, "lifecycle", {"phase": "error", "error": res.get("err") or "gateway_offline",
                                      "attempts": res.get("attempts") or [], "trace_id": tid})
            return None  # 全供应商失败（如限流/宕机）→ caller 退化
        # 故障转移留痕：本次实际由哪个供应商应答，切了几次（排障/对账用）。
        if len(res.get("attempts") or []) > 1 or res.get("provider") not in (None, provider):
            _emit(emit, "lifecycle", {
                "phase": "failover", "provider": res.get("provider"),
                "attempts": res.get("attempts") or [], "trace_id": tid,
            })
        u = res.get("usage")
        if u:
            pt = (u.get("prompt_tokens") or 0)
            ct = (u.get("completion_tokens") or 0)
            guard.record_tokens(pt + ct)
            # 成本记账：原实现从不调用 record_cost，导致 BudgetGuard.max_cost
            # 闸门（RUN_MAX_COST）恒不触发 —— 单次运行成本完全失控。
            # 优先用网关回传的真实 cost；否则按 token 数 × 配置单价估算。
            try:
                cost = u.get("cost")
                if cost is None:
                    cost = _estimate_cost(pt, ct, model)
                guard.record_cost(cost)
            except Exception:
                pass
        msg_content = res["text"]
        tool_calls = res["tool_calls"]
        last_assistant = msg_content or last_assistant
        if msg_content:
            _emit(emit, "assistant", {"delta": msg_content})

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

        inner_break = False
        pending_approval = None
        for tc in tool_calls:
            name, args = tc["name"], (tc["arguments"] or {})
            decision, reason = guard.check_step(action_key=name)  # 含失控循环检测
            if decision == "open":
                circuit_open, circuit_reason = True, reason
                inner_break = True
                break
            _emit(emit, "tool", {"event": "call", "tool": name, "args": args})
            with observability.span("tool:" + name, kind="tool", tenant_id=tenant_id) as tsp:
                r = tools_registry.run_tool_governed(name, args, tenant_id=tenant_id, session_id=None)
                if "error" in r:
                    tsp.set_status("error")
            # 🔴 审批卡识别（2026-09-30 加固）：
            # run_tool_governed 命中审批门时返回 {"status":"pending","approval_id":...}，
            # 原实现走到最后的 json.dumps 兜底分支，把整份审批单当工具结果喂回模型，
            # 模型会误判"工具已执行完"，导致 HITL 形同虚设。
            # 这里显式识别：回灌明确的「待人工审批」观察并**结束本轮循环**。
            if isinstance(r, dict) and r.get("status") == "pending":
                aid = r.get("approval_id")
                pending_approval = {"approval_id": aid, "tool": name, "args": args}
                out = ("【待人工审批】工具「%s」因高危/需确认已被安全审批门挂起，尚未执行。"
                       "审批单号 %s。请告知用户：需先在审批中心完成审批，"
                       "审批通过后系统会自动续跑该动作。" % (name, aid))
                _emit(emit, "tool", {"event": "pending", "tool": name, "approval_id": aid})
                used_tools.append(name)
                loop_trace.append({"tool": name, "args": args, "pending_approval": aid})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "name": name,
                                 "content": out[:1600]})
                inner_break = True
                break
            if "result" in r:
                out = str(r["result"])
            elif "content" in r:
                out = str(r["content"])
            elif "error" in r:
                out = "工具执行出错：" + str(r["error"])
            else:
                out = json.dumps(r, ensure_ascii=False)
            _emit(emit, "tool", {"event": "result", "tool": name, "result": out[:600]})
            used_tools.append(name)
            loop_trace.append({"tool": name, "args": args, "result": out[:600]})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": out[:1600]})
        if inner_break:
            # 挂起在审批门：让模型基于"待审批"观察再生成一次最终答复（告知用户），
            # 但**不得**继续执行后续工具调用。
            if pending_approval is not None:
                try:
                    with observability.span("llm:pending_notice", kind="llm",
                                            tenant_id=tenant_id) as psp:
                        nres = _llm_chat(system, messages, [], tenant_id=tenant_id,
                                         provider=provider, model=model)
                    if nres.get("ok") and nres.get("text"):
                        final_text = nres["text"]
                        _emit(emit, "assistant", {"delta": nres["text"]})
                except Exception:
                    pass
            break

    if not final_text:
        final_text = last_assistant or "（未能生成最终回答）"

    _emit(emit, "lifecycle", {"phase": "end", "tool_calls_used": used_tools, "trace_id": tid})

    result = {
        "answer": final_text,
        "mode": "agent",
        "model": model or config.LLM_MODEL,
        "tool_calls_used": used_tools,
        "loop_trace": loop_trace,
        "memories_used": bool(memories),
        "trace_id": tid,
    }
    if pending_approval:
        # 上层据此渲染「审批卡」UI；审批通过后带 approval_id 重跑触发 resume。
        result["pending_approval"] = pending_approval
    if circuit_open:
        result["circuit_open"] = True
        result["circuit_reason"] = circuit_reason
        # 告警：写 SOC 链（best-effort，绝不因失败影响返回）
        try:
            soc_audit.log({
                "type": "circuit_breaker",
                "reason": circuit_reason,
                "tenant_id": tenant_id,
                "steps": guard.steps,
                "tokens": guard.tokens,
                "cost": round(guard.cost, 6),
                "trace_id": tid,
            })
        except Exception:
            pass
    return result
