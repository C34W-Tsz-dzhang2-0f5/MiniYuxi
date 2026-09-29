"""域10 记忆压缩（slim）验收测试。

不依赖 requests / LLM / DB：纯本地启发式，离线可跑。
用法：python tests/_verify_memory_slim.py
退出码 0 = 全部通过；非 0 = 有失败。
"""
import os
import sys

# 自定位项目根（tests/ 的上级），避免依赖 cwd / 中文路径 PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import memory_slim


def _mk(n, role="user", base="消息"):
    return [{"role": role, "content": f"{base}-{i}"} for i in range(n)]


def test_short_returns_as_is():
    msgs = _mk(5)
    out = memory_slim.slim_messages(msgs)
    assert out == msgs, "短历史应原样返回"
    print("[1] 短历史原样返回 OK")


def test_empty():
    assert memory_slim.slim_messages([]) == []
    assert memory_slim.slim_messages(None) == []
    print("[2] 空/None 返回空列表 OK")


def test_long_exceeds_turns():
    msgs = _mk(40)  # 远超 RECENT_KEEP=8 且 > max_turns=24
    out = memory_slim.slim_messages(msgs)
    # 最近 8 条原文保留
    assert len(out) == 9, f"应为 1 摘要 + 8 原文，实际 {len(out)}"
    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith(memory_slim.SLIM_PREFIX)
    assert out[-1]["content"] == "消息-39"
    assert out[1]["content"] == "消息-32"  # 最近 8 条从 32 起
    print("[3] 超轮数 → 摘要+最近8条 OK")


def test_char_budget_triggers_roll():
    # 每条 200 字 × 30 条 = 6000 字，未超 char_budget；但 30 > RECENT_KEEP=8 且 > max_turns=24
    big = [{"role": "user", "content": "x" * 200} for _ in range(30)]
    out = memory_slim.slim_messages(big)
    assert len(out) == 9, f"应触发压缩，实际 {len(out)}"
    print("[4] 字符/轮数预算触发滚卷 OK")


def test_recent_keep_respected():
    msgs = _mk(100)
    out = memory_slim.slim_messages(msgs)
    # 最近 8 条必须是原文尾段
    assert [m["content"] for m in out[1:]] == [f"消息-{i}" for i in range(92, 100)]
    print("[5] 最近 recent_keep 条原文保活 OK")


def test_summarizer_used():
    calls = {}

    def fake_summary(text):
        calls["text"] = text
        return "【语义摘要】用户连续咨询了考勤与绩效问题。"

    msgs = _mk(30)
    out = memory_slim.slim_messages(msgs, summarizer=fake_summary)
    assert out[0]["content"] == memory_slim.SLIM_PREFIX + "【语义摘要】用户连续咨询了考勤与绩效问题。"
    assert "text" in calls, "应调用 summarizer"
    print("[6] summarizer 回调生效 OK")


def test_summarizer_failure_fallback():
    def boom(text):
        raise RuntimeError("llm down")

    msgs = _mk(30)
    out = memory_slim.slim_messages(msgs, summarizer=boom)
    # 回调失败必须安全回退到启发式，不抛错、不丢摘要
    assert out[0]["content"].startswith(memory_slim.SLIM_PREFIX)
    assert "已滚卷" in out[0]["content"], "应回退到启发式面包屑"
    print("[7] summarizer 抛错 → 启发式回退 OK")


def test_agent_loop_filter_keeps_summary():
    """模拟 agent_loop 的接收过滤：user/assistant 原文 + SLIM_PREFIX 摘要都应保留。"""
    out = memory_slim.slim_messages(_mk(40))
    kept = []
    for h in out:
        role = h.get("role")
        content = h.get("content") or ""
        if (role in ("user", "assistant") or content.startswith(memory_slim.SLIM_PREFIX)) and content:
            kept.append(h)
    assert len(kept) == len(out), "agent_loop 过滤不应丢弃压缩摘要"
    assert kept[0]["content"].startswith(memory_slim.SLIM_PREFIX)
    print("[8] agent_loop 过滤保留压缩摘要 OK")


if __name__ == "__main__":
    test_short_returns_as_is()
    test_empty()
    test_long_exceeds_turns()
    test_char_budget_triggers_roll()
    test_recent_keep_respected()
    test_summarizer_used()
    test_summarizer_failure_fallback()
    test_agent_loop_filter_keeps_summary()
    print("\nALL MEMORY_SLIM TESTS PASSED")
    sys.exit(0)
