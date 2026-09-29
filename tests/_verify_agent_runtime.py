# -*- coding: utf-8 -*-
"""域1 进程级 agent manager 验收（目标任务书 2.1 域1）。

验收口径：
  1. 并发多 session（线程池不互锁）；
  2. 长会话累积（跨请求 resume，messages 持久化到 session）；
  3. cancel 标记（协作式）；
  4. prune_idle 清理闲置（防内存泄漏）。

用 mock 替代 agent_loop.run，离线（无 LLM Key）即可全绿。
退出码：0 = 全部通过；1 = 有失败。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sys
from unittest.mock import patch, MagicMock

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    # 测试隔离：本机测试环境缺 requests 时注入 mock（真实 CI/运行环境有真实包）
    sys.modules["requests"] = MagicMock()

from core import agent_runtime

CONTRACT_STR = ("session_id", "tenant_id", "status", "turns", "created_at", "last_active")


def check(name, ok, detail=""):
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))
    return 0 if ok else 1


def fake_run(system, user_prompt, history=None, tenant_id=None, memories=None):
    """模拟 ReAct 大脑：回声 + 记录被传入的 history（验证长会话累积）。"""
    return {
        "answer": f"回声:{user_prompt}",
        "mode": "agent",
        "model": "fake",
        "tool_calls_used": [],
        "loop_trace": [],
        "memories_used": False,
        "_history_len": len(history or []),
    }


def main():
    print("=" * 70)
    print("域1 · 进程级 Agent 运行时管理器 验收")
    print("=" * 70)
    fails = 0
    am = agent_runtime.AgentManager

    # ---- 1. 并发多 session ----
    print("\n[1] 并发多 session（线程池不互锁）")
    with patch.object(agent_runtime.agent_loop, "run", fake_run):
        futs = []
        for i in range(3):
            sid = f"conv-{i}"
            am.create(sid, "t1")
            f = am.submit(sid, f"问题{i}")
            futs.append((sid, f))
        results = [(sid, (f.result(timeout=5) if f else None)) for sid, f in futs]
        ok_all = all(r and r.get("ok") for _, r in results)
        fails += check("3 个并发 session 均返回 ok", ok_all, str([r.get("ok") for _, r in results]))

    # ---- 2. 长会话累积 ----
    print("\n[2] 长会话累积（跨请求 resume）")
    with patch.object(agent_runtime.agent_loop, "run", fake_run):
        sid = "long-1"
        am.create(sid, "t1")
        r1 = am.submit(sid, "第一轮").result(timeout=5)
        s = am.get(sid)
        turns1 = s.to_dict()["turns"]
        r2 = am.submit(sid, "第二轮").result(timeout=5)
        s = am.get(sid)
        turns2 = s.to_dict()["turns"]
        fails += check("第一轮后 turns=1", turns1 == 1, f"turns1={turns1}")
        fails += check("第二轮后 turns=2（累积）", turns2 == 2, f"turns2={turns2}")
        # 第二轮被传入的 history 应包含第一轮上下文（user+assistant）
        fails += check("第二轮 history 含第一轮（len=2）", r2.get("_history_len") == 2,
                       f"hist_len={r2.get('_history_len')}")
        fails += check("累积 messages 长度=4", len(s.messages) == 4, f"len={len(s.messages)}")

    # ---- 3. cancel ----
    print("\n[3] cancel 标记")
    sid = "cancel-1"
    am.create(sid, "t1")
    am.cancel(sid)
    s = am.get(sid)
    fails += check("cancel 后 status=cancelled", s.status == "cancelled", f"status={s.status}")

    # ---- 4. prune_idle ----
    print("\n[4] prune_idle 清理闲置")
    sid = "idle-1"
    am.create(sid, "t1")
    s = am.get(sid)
    s.last_active = time.time() - 9999  # 注入过期
    n = am.prune_idle(max_idle=3600)
    fails += check("过期 session 被清理", am.get(sid) is None and n >= 1, f"pruned={n}")

    # ---- 5. to_dict 字段契约 ----
    print("\n[5] to_dict 字段契约")
    sid = "dict-1"
    am.create(sid, "t1")
    d = am.get(sid).to_dict()
    missing = [k for k in CONTRACT_STR if k not in d]
    fails += check("to_dict 含全部约定字段", len(missing) == 0, ("缺:" + ",".join(missing) if missing else ""))

    print()
    print("=" * 70)
    if fails:
        print(f"结论: 失败 —— {fails} 项")
        return 1
    print("结论: 通过 —— 进程级 agent manager 并发/长会话/cancel/prune/to_dict 全绿。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
