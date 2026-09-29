# 域10 改造：记忆压缩 / slim（M5）

> 任务书判定：🟡 需改造。改造项：给记忆加 token 预算 / 摘要压缩，替换硬编码 `MAX_HISTORY` 盲截断。
> 优先级：P0（纯内核，无外部依赖）。
> 落地日期：2026-09-28（与域1 同批 P0）。

## 1. 现状核实（改造前）

`core/agent_loop.py:51` 主对话路径：

```python
for h in (history or [])[-rag.MAX_HISTORY:]:          # 硬截断：只留最近 10 条
    ...
    messages.append({"role": role, "content": content[:rag.MAX_HISTORY_CHARS]})  # 每条 800 字
```

- `rag.MAX_HISTORY = 10` / `MAX_HISTORY_CHARS = 800`（`rag.py:21-22`、`gateway.py:14-15` 重复定义）。
- **痛点**：长会话早期上下文被静默丢弃；预算写死不可配；无语义压缩，纯盲截。
- `memory.py`（T3 长期记忆）与 `memory_v2.py`（M4 经验蒸馏）**只管持久化沉淀，不管实时历史压缩** —— 域10 的缺口正是"实时对话历史的预算压缩"。

## 2. 目标

- 用预算感知的压缩替代盲截断：保活最近 N 条原文，超预算的旧消息滚卷为一条压缩摘要。
- 预算可配置（轮数 + 字符）。
- 可选 LLM 语义摘要（调用方注入 egress 合规网关），默认启发式零依赖。
- 不触碰红线文件（`agent.py`/`rag.py`/`db.py`）。

## 3. 新增文件

### `core/memory_slim.py`（新增）
- `slim_messages(messages, *, max_turns, char_budget, recent_keep, summarizer)` —— 纯函数，零外部依赖。
- 常量：`DEFAULT_MAX_TURNS=24`、`DEFAULT_CHAR_BUDGET=12000`、`RECENT_KEEP=8`、`SLIM_PREFIX="[历史压缩摘要] "`。
- 返回结构：超预算 → `[{role:"system", content: SLIM_PREFIX+摘要}] + 最近 recent_keep 条原文`；未超 → 原样。
- `summarizer` 回调抛错时安全回退启发式，不崩主链路。

### 接入点：`core/agent_loop.py`（非红线文件，可接受）
将 `history[-rag.MAX_HISTORY:]` 替换为 `memory_slim.slim_messages(history)`，并把接收过滤放宽为
`role in ("user","assistant") 或 content.startswith(SLIM_PREFIX)`，确保压缩摘要不被丢弃。

> 选择 agent_loop 而非 gateway/model_hub 作为接入点：agent 长会话是域10 主场景；
> gateway/model_hub 是 RAG/评测等短历史路径，保持旧行为不动，控制爆破半径。

## 4. 测试

`tests/_verify_memory_slim.py`（8 项，离线纯本地）：
1. 短历史原样返回
2. 空 / None 返回空
3. 超轮数 → 1 摘要 + 最近 8 条
4. 字符/轮数预算触发滚卷
5. 最近 recent_keep 条原文保活
6. summarizer 回调生效
7. summarizer 抛错 → 启发式回退
8. agent_loop 过滤保留压缩摘要

运行：`python tests/_verify_memory_slim.py` → 全绿 exit 0。

## 5. 红线自检（任务书 §6）

- [x] 未改 `agent.py` / `rag.py` / `db.py`
- [x] 无新增网络/LLM 调用；LLM 摘要为可选回调，由调用方自行走 `core/egress.py`
- [x] 仅新增 `memory_slim.py` + 改动非红线文件 `agent_loop.py`
- [x] 测试离线可跑，不依赖 requests / DB

## 6. 风险分级

| 项 | 等级 | 说明 |
|---|---|---|
| 改 agent_loop 接入 slim | 🟢 低 | 纯本地、可回退、单点接入 |
| summarizer 走 LLM | 🟡 中 | 默认关闭；启用时须经 egress 网关收口（调用方负责） |
| 摘要占位误吞关键信息 | 🟢 低 | recent_keep 保活最新 8 轮；旧消息留首尾面包屑，可追问 |

## 7. Octop 对照（待 clone 完成后补）

Octop Memory 的 `memory slim` 思路：把超出预算的对话历史压缩为紧凑摘要以省 token。
MiniYuxi 采用等效但更克制的增量方案（启发式滚卷 + 可选 LLM 摘要），与域1 的"线程池增量、非全栈 asyncio"
哲学一致：零侵入、可立即验证、不破坏同步调用栈与 egress 收口。

## 8. 交付清单

- [x] `core/memory_slim.py`
- [x] `core/agent_loop.py`（接入 slim）
- [x] `tests/_verify_memory_slim.py`
- [x] 本方案文档
