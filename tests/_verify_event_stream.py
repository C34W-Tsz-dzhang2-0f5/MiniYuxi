"""验证 01 号票：Agent 事件流（agent_loop emit + chat_stream SSE 帧）。

Red-Green-Refactor（vibe-coding-workflow S2）：本文件先写、先失败，再实现。
契约（CONTEXT.md §三）：
  事件三型 lifecycle / tool / assistant，禁止别名。
  SSE 帧格式：`event: <type>\ndata: <json>\n\n`。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import agent_loop, gateway, config, wb_workbench  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  <- {extra}" if extra else ""))
        FAILS.append(name)


# ---------- 公共夹具：假网关（第一次返回工具调用，第二次返回终答） ----------
_real_cwt = gateway.chat_with_tools
_real_enabled = config.llm_enabled


def _install_fake_gateway():
    state = {"n": 0}

    def fake(system, messages, tools, history=None, provider=None, tenant_id=None, model=None):
        state["n"] += 1
        if state["n"] == 1:
            return {"ok": True, "text": "我先看下时间", "usage": None,
                    "tool_calls": [{"id": "tc1", "name": "current_time", "arguments": {}}]}
        return {"ok": True, "text": "现在是 2026 年。", "tool_calls": [], "usage": None}

    gateway.chat_with_tools = fake
    config.llm_enabled = lambda: True
    return state


def _restore():
    gateway.chat_with_tools = _real_cwt
    config.llm_enabled = _real_enabled


print("=" * 60)
print("A. agent_loop.run(emit=...) 产出三型事件且顺序正确")
print("=" * 60)

events = []
try:
    _install_fake_gateway()
    res = agent_loop.run("sys", "现在几点", tenant_id="default", emit=events.append)
finally:
    _restore()

types = [e.get("type") for e in events]
print("  events:", json.dumps(events, ensure_ascii=False)[:400])

check("emit 收到事件（非空）", len(events) > 0, str(len(events)))
check("含 lifecycle 事件", "lifecycle" in types, str(types))
check("含 tool 事件", "tool" in types, str(types))
check("含 assistant 事件", "assistant" in types, str(types))
check("首事件为 lifecycle:start",
      events and events[0].get("type") == "lifecycle" and events[0].get("payload", {}).get("phase") == "start",
      json.dumps(events[:1], ensure_ascii=False))
check("末事件为 lifecycle:end",
      events and events[-1].get("type") == "lifecycle" and events[-1].get("payload", {}).get("phase") == "end",
      json.dumps(events[-1:], ensure_ascii=False))

tool_events = [e for e in events if e.get("type") == "tool"]
check("tool 事件含 call 与 result",
      any(t.get("payload", {}).get("event") == "call" for t in tool_events)
      and any(t.get("payload", {}).get("event") == "result" for t in tool_events),
      json.dumps(tool_events, ensure_ascii=False)[:300])
check("tool:call 带工具名 current_time",
      any(t.get("payload", {}).get("tool") == "current_time" for t in tool_events))
check("返回值结构未变（仍含 answer/mode/tool_calls_used）",
      isinstance(res, dict) and "answer" in res and "tool_calls_used" in res,
      str(type(res)))

print()
print("=" * 60)
print("B. 不传 emit 时行为与返回值不变（向后兼容）")
print("=" * 60)

try:
    _install_fake_gateway()
    res2 = agent_loop.run("sys", "现在几点", tenant_id="default")
finally:
    _restore()
check("不传 emit 仍返回 dict", isinstance(res2, dict) and "answer" in res2, str(type(res2)))
check("不传 emit 不报错", res2.get("answer") is not None)

print()
print("=" * 60)
print("C. wb_workbench.chat_stream 产出合法 SSE 帧")
print("=" * 60)

frames = []


def fake_run(system, user_prompt, history=None, tenant_id=None, memories=None,
             trace_id=None, provider=None, model=None, emit=None):
    if emit:
        emit({"type": "lifecycle", "payload": {"phase": "start"}})
        emit({"type": "assistant", "payload": {"delta": "你好"}})
        emit({"type": "tool", "payload": {"event": "call", "tool": "current_time"}})
        emit({"type": "tool", "payload": {"event": "result", "tool": "current_time", "result": "2026"}})
        emit({"type": "lifecycle", "payload": {"phase": "end"}})
    return {"answer": "你好，现在是 2026 年。", "mode": "agent", "model": "test",
            "tool_calls_used": ["current_time"], "loop_trace": [], "memories_used": False,
            "trace_id": "tr_x"}


_real_run = agent_loop.run
agent_loop.run = fake_run
try:
    frames = list(wb_workbench.chat_stream("default", "你好", mode="agent"))
finally:
    agent_loop.run = _real_run

joined = "".join(frames)
check("chat_stream 产出帧", len(frames) > 0, str(len(frames)))
check("帧含 event: 与 data: 行", "event: " in joined and "data: " in joined)
check("帧以空行分隔（SSE 规范）", "\n\n" in joined)


def _parse(fr):
    out = []
    for block in fr.split("\n\n"):
        if not block.strip():
            continue
        ev = {"event": None, "data": None}
        for line in block.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[7:]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[6:])
        out.append(ev)
    return out


parsed = _parse(joined)
ptypes = [p["event"] for p in parsed]
check("SSE 帧可解析且 event 型合法",
      all(p["event"] in ("lifecycle", "tool", "assistant", "final") for p in parsed),
      str(ptypes))
check("含 lifecycle/tool/assistant 三型",
      "lifecycle" in ptypes and "tool" in ptypes and "assistant" in ptypes, str(ptypes))

print()
print("=" * 60)
print("D. API 路由 /api/wb/chat/stream 已注册")
print("=" * 60)

try:
    import api
    paths = [getattr(r, "path", "") for r in api.app.routes]
    check("路由 /api/wb/chat/stream 存在", "/api/wb/chat/stream" in paths,
          str([p for p in paths if "chat" in p]))
    check("原 /api/wb/chat 仍在（未破坏）", "/api/wb/chat" in paths)
except Exception as e:
    check("api 可导入", False, f"{type(e).__name__}: {e}")

print()
print("=" * 60)
if FAILS:
    print(f"FAILED: {len(FAILS)} 项 -> " + "; ".join(FAILS))
    sys.exit(1)
print("ALL PASS（事件流 01 号票通过）")
