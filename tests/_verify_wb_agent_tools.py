"""验证：复刻页主对话（/api/wb/chat → wb_workbench.chat）在 agent 模式下真正执行工具。

背景（2026-09-29 修）：此前 wb_workbench.chat 只做「单次 LLM 生成」，
从不调用 agent_loop，工具清单形同虚设——表现为「对话框装技能装不了 / 写代码写不了」。

本测试锁定三件事：
  A. agent 模式 → 必须走 agent_loop.run（真正执行工具），且结果回传 tool_calls_used；
  B. ask 模式 → 不得走 agent_loop（保持纯问答语义）；
  C. agent 模式的 system prompt 必须列出可用工具 + 「必须真正调用」强制指令；
  D. 模型透传：gateway.chat_with_tools / agent_loop.run 支持指定 model（不丢多模型选择）。
"""
import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import wb_workbench, agent_loop, gateway, tools_registry  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  <- {extra}" if extra else ""))
        FAILS.append(name)


print("=" * 60)
print("A. agent 模式必须走 agent_loop（工具真正执行）")
print("=" * 60)

calls = {"n": 0, "kwargs": {}}
_real_run = agent_loop.run


def _fake_run(system, user_prompt, history=None, tenant_id=None, memories=None,
              trace_id=None, provider=None, model=None, emit=None):
    calls["n"] += 1
    calls["kwargs"] = {"tenant_id": tenant_id, "provider": provider, "model": model}
    return {
        "answer": "已调用 skill.install 完成安装。",
        "mode": "agent",
        "model": model or "test-model",
        "tool_calls_used": ["skill.install"],
        "loop_trace": [{"tool": "skill.install", "args": {"source": "x/y"}, "result": "ok"}],
        "memories_used": False,
        "trace_id": "tr_test",
    }


agent_loop.run = _fake_run
try:
    out = wb_workbench.chat("default", "帮我安装这个技能", mode="agent")
finally:
    agent_loop.run = _real_run

check("agent 模式调用了 agent_loop.run", calls["n"] == 1, f"实际 {calls['n']} 次")
check("工具调用记录回传（tool_calls_used）",
      out.get("tool_calls_used") == ["skill.install"], str(out.get("tool_calls_used")))
check("loop_trace 回传", bool(out.get("loop_trace")))
check("trace_id 回传（要素④可观测性贯通）", out.get("trace_id") == "tr_test", str(out.get("trace_id")))
check("结果非降级", out.get("ok") is True and not out.get("degraded"), str(out.get("err")))
check("tenant_id 正确透传", calls["kwargs"].get("tenant_id") == "default", str(calls["kwargs"]))

print()
print("=" * 60)
print("B. ask 模式不得走 agent_loop（保持纯问答）")
print("=" * 60)

calls["n"] = 0
agent_loop.run = _fake_run
try:
    wb_workbench.chat("default", "这是什么", mode="ask")
finally:
    agent_loop.run = _real_run

check("ask 模式未调用 agent_loop", calls["n"] == 0, f"实际 {calls['n']} 次")

print()
print("=" * 60)
print("C. agent 模式 system prompt 必须含工具清单 + 强制真正调用")
print("=" * 60)

sys_agent = wb_workbench._build_system_prompt(mode="agent", allow_full_access=True)
check("列出 skill.install", "skill.install" in sys_agent)
check("列出 skill.uninstall", "skill.uninstall" in sys_agent)
check("含『必须真正调用』强制指令", "真正调用" in sys_agent)
check("含 npx skills add 的 select 约定", "select" in sys_agent)

sys_ask = wb_workbench._build_system_prompt(mode="ask", allow_full_access=True)
check("ask 模式不注入工具清单", "skill.install" not in sys_ask)

inv = tools_registry.tool_inventory_text()
check("tool_inventory_text 非空", bool(inv.strip()))
check("tool_inventory_text 覆盖内置工具", "current_time" in inv and "calc" in inv)

print()
print("=" * 60)
print("D. 模型透传（不丢多模型选择）")
print("=" * 60)

gw_params = inspect.signature(gateway.chat_with_tools).parameters
check("gateway.chat_with_tools 支持 model 参数", "model" in gw_params)
check("gateway payload 使用 model or config.LLM_MODEL",
      "model or config.LLM_MODEL" in inspect.getsource(gateway.chat_with_tools))

al_params = inspect.signature(agent_loop.run).parameters
check("agent_loop.run 支持 provider 参数", "provider" in al_params)
check("agent_loop.run 支持 model 参数", "model" in al_params)
check("agent_loop 把 model 传给 gateway",
      "model=model" in inspect.getsource(agent_loop.run))

print()
print("=" * 60)
if FAILS:
    print(f"FAILED: {len(FAILS)} 项 -> " + "; ".join(FAILS))
    sys.exit(1)
print("ALL PASS（wb 主对话 Agent 工具链路已打通）")
