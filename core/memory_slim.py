"""M5 记忆压缩（slim）：在 token/字符预算内压缩历史消息，替代硬编码盲截断。

域10 🟡 痛点
------------
`agent_loop.run` / `gateway._messages` 用 `rag.MAX_HISTORY=10` + 每条 `MAX_HISTORY_CHARS=800`
盲截断：长会话早期上下文被静默丢弃，且预算不可配置、无法语义压缩。

本模块提供 `slim_messages()`：
- 始终保活最近 `RECENT_KEEP` 条原文；
- 其余旧消息超出预算（条数 > max_turns 或 字符 > char_budget）时，滚卷为一条
  "压缩摘要"占位（含条数 + 角色分布 + 首尾片段），避免盲删丢上下文；
- 可选 `summarizer(rolled_text)->str` 回调：由调用方注入经 egress 网关的 LLM 摘要，
  实现真·语义压缩（默认 None = 启发式，纯本地零依赖、不触碰 egress 收口）。

设计红线（任务书 §6）
--------------------
- 本文件为**新增**，不修改 `core/agent.py` / `core/rag.py` / `core/db.py`；
- `slim_messages` 是纯函数、零外部依赖，调用方（agent_loop）**可选接入**；
- 不做任何网络/LLM 调用，因此不涉及 `core/egress.py` 收口（LLM 摘要由调用方自行收口）。
"""
from __future__ import annotations

SLIM_PREFIX = "[历史压缩摘要] "

DEFAULT_MAX_TURNS = 24       # 触发压缩前的原文轮数阈值（比旧 10 更宽松）
DEFAULT_CHAR_BUDGET = 12000  # 整体字符预算（启发式，约 3~4k token）
RECENT_KEEP = 8              # 无论如何保留最近原文条数


def _est_chars(messages: list) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def slim_messages(
    messages: list | None,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    recent_keep: int = RECENT_KEEP,
    summarizer=None,
) -> list:
    """在预算内压缩历史，返回可直接喂给 gateway/model_hub 的 messages 列表。

    返回结构：
    - 未超预算：原样返回（list of {role, content}）；
    - 超预算：返回 `[{role:"system", content: SLIM_PREFIX+摘要}] + 最近 recent_keep 条原文`。

    `summarizer`：可选回调 `fn(rolled_text)->str`。提供则用它生成语义摘要（调用方负责
    走 egress 网关）；否则用启发式面包屑。回调抛错时安全回退到启发式。
    """
    if not messages:
        return []
    msgs = [m for m in messages if isinstance(m, dict)]
    if len(msgs) <= recent_keep:
        return msgs  # 未达保留阈值，原样返回

    recent = msgs[-recent_keep:]
    old = msgs[:-recent_keep]
    total = _est_chars(msgs)
    over = (len(msgs) > max_turns) or (total > char_budget)
    if not over:
        return msgs

    rolled_text = _roll_text(old)
    summary = rolled_text
    if summarizer:
        try:
            s = (summarizer(rolled_text) or "").strip()
            if s:
                summary = s
        except Exception:
            summary = rolled_text  # 回调失败 → 回退启发式，不崩主链路

    return [{"role": "system", "content": SLIM_PREFIX + summary}] + recent


def _roll_text(old: list) -> str:
    """启发式滚卷：条数 + 角色分布 + 首尾片段，作为语义摘要缺失时的面包屑。"""
    n = len(old)
    roles: dict = {}
    for m in old:
        r = m.get("role", "?")
        roles[r] = roles.get(r, 0) + 1
    role_desc = "，".join(f"{k}×{v}" for k, v in roles.items())
    first = (old[0].get("content") or "")[:120]
    last = (old[-1].get("content") or "")[:120]
    return (
        f"已滚卷 {n} 条历史消息（{role_desc}）。"
        f"最早片段：{first} …… 最近片段：{last} ……"
        f"（更早细节已压缩，必要时可向用户追问确认）"
    )
