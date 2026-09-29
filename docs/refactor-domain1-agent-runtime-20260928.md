# 域1 改造方案：进程级 Agent 运行时管理器

> 来源：目标任务书 2.1 总对照表 域1（Agent 运行时/进程管理，🟡 部分对齐）
> 行动建议原文：「复用 ReAct+状态机思路；补『进程级 agent manager』支撑多并发长会话（异步化）」
> 关联：Octop `HarnessAgentManager`(per-user) + `AgentRuntime`(per-agent)
> 红线：不碰 `core/agent.py` / `core/rag.py` / `core/db.py`；外部调用必过 `core/egress.py`

---

## 结论先行

MiniYuxi 当前 `core/agent_loop.run()` 是**同步单轮阻塞式** ReAct，每次调用都重建 messages、**无跨请求会话保活、无并发管理**。本改造**新增** `core/agent_runtime.py`（不碰 `agent.py` 指纹），提供进程级 `AgentManager` 单例 + `AgentSession`（长会话保活）+ `ThreadPoolExecutor` 并发，复用现有 ReAct 大脑。

---

## 现状（已核实）

- `core/agent_loop.py:42` `run(system, user_prompt, history, tenant_id, memories)`：
  - 同步、串行 `MAX_LOOPS=6` 轮、阻塞调用线程；
  - 每次调用都从 `history` 重建 messages，**无 session 级状态**，无法跨请求 resume；
  - 离线/网关失败返回 `None`（由 caller 退化）。
- 无进程级 agent 实例管理、无并发控制、无长会话 resume —— 即「进程级 agent manager」整体缺失。

## 目标

1. 进程级单例 `AgentManager`，管理多个 `AgentSession`（按 tenant/session 维度）；
2. 并发：线程池支撑多会话并行（**不阻塞 Web 请求线程**）；
3. 长会话：`AgentSession` 累积 messages，跨请求 resume；
4. 可取消 / 可列举 / 闲置清理（防内存泄漏）；
5. 守红线：不碰 `agent.py/rag.py/db.py`；外部调用仍经 `agent_loop → gateway`（egress 收口不变）。

---

## 关键设计决策

- **线程池而非全栈 asyncio**：MiniYuxi 全栈同步（`gateway`/`rag`/`tools_registry` 均为同步 `requests`），强行 asyncio 化风险高、工作量大、易破坏 egress 收口与同步栈。**线程池增量方案**复用同步栈、零侵入、即时可验。
- **新增模块不碰指纹**：`AgentManager`/`AgentSession` 全在 `agent_runtime.py`，`agent.py` 一行不动。
- **长会话保活**：`session.messages` 累积；进程级单例保活即跨请求保活（无需立即落库）。将来可选映射到持久化对话线程（标注待补）。
- **cancel 协作式**：Python `Future` 无法强制中断运行中的同步 loop，cancel 仅标记 + 运行结束后由 manager 清理（运行中轮次不强制终止；与单进程本地 Agent 定位匹配，可接受）。

---

## 文件清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `core/agent_runtime.py` | **新建** | `AgentSession` + `AgentManager` + 进程级 executor + `prune_idle` |
| `tests/_verify_agent_runtime.py` | **新建** | 并发 / 长会话累积 / cancel / prune |
| `api.py` | 编辑（非指纹） | 新增 `POST /api/agent/session` + `/submit` + `/status` + `/cancel` + `/list` |
| （可选）`core/db.py` 持久化 hook | 调用公开 API | 会话落库以增强断线恢复（非必须，本轮 MVP 不做） |

---

## 测试要点

- **并发**：同时 `submit` 3 个 session，断言都返回（不互锁、不丢）；
- **长会话**：同一 session 连续两轮，断言 `messages` 累积、第二轮可见第一轮上下文；
- **cancel**：`submit` 后立即 `cancel`，断言 `status` 进入 `cancelled` 标记（idle/running 协作）；
- **prune_idle**：注入过期 session，断言被清理、计数正确。

> 离线环境（`config.llm_enabled()=False`）下 `agent_loop.run` 返回 `None` → session 标记 `error/offline`，测试不依赖真实 LLM Key 即可全绿。

---

## 红线合规自检

- ✅ 不碰 `agent.py` / `rag.py` / `db.py`（仅 `import` 复用的 `agent_loop`）；
- ✅ 外部调用经 `agent_loop → gateway`（egress 收口链路不变）；
- ✅ 新增仅 `agent_runtime.py` + `api.py` 路由（均非指纹）。

---

## 风险

- 🟡 中等：线程池并发下 `agent_loop` 内部共享状态需确认线程安全（`gateway.chat_with_tools` 若用全局 `requests.Session` 单例，需确认线程安全；必要时每线程独立 session）；
- 🟡 中等：cancel 无法强制中断运行中的同步 loop（协作式，标记后等结束）。

---

## Octop 对照（待 clone 完成后补细节）

- Octop：`HarnessAgentManager`(per-user) + `AgentRuntime`(per-agent)，**asyncio 单进程**模型；
- MiniYuxi 选**线程池增量方案**，理由见上（全栈同步、egress 收口、零侵入、即时可验）。
