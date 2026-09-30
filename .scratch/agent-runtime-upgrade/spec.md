# Spec: Agent 运行时升级（事件流 / 代码工具 / Swarm / Heartbeat）

> 来源：`docs/openclaw-architecture-study-20260930.md` §7 落地路线 P0–P5（对标 OpenClaw 企业级运行时）
> 状态：`ready-for-agent`
> 路由：`vibe-coding-workflow` 主流程 → S1（本 spec 由研究文档综合已知产出）→ `to-tickets` 拆 5 票 → S2/S3 每票 契约先行 + 小提交 → S4 真实回归 → S5 并行评审 + Jev → S6 资产化
> 决策（阿长 2026-09-30 拍板）：写代码=**B+C**（写文件 HITL+白名单 + 接 `coding_agent`）；前端**不迁 React**，只补 SSE 事件流 + 场景技能卡；**重出 MSI**；运行时顺序 **SSE → Lane(已存在,补齐) → Swarm → Heartbeat**

## Problem Statement

MiniYuxi 内核（`agent_loop.py`）已是同构 ReAct 循环，会话级 Lane（`agent_runtime.py` 同会话串行）也已存在。但与 OpenClaw 对标，**企业级运行时仍缺四块**，直接导致「网页版/桌面版体验不完整」：

1. **无事件流**：`agent_loop.run()` 是同步黑盒，前端只能等最终文本，看不到「思考中 / 调了哪个工具 / 工具返回了什么」——这是「看起来像不能用」的最大体感来源（对标 OpenClaw 的 `lifecycle`/`tool`/`assistant` 三型事件）。
2. **无代码/文件工具**：工具清单只有 `calc/current_time/kb_search/count_docs/web_search/video.generate/skill.*`，「在对话框写代码」做不到（`coding_agent` 只暴露成 REST 端点，未进工具链）。
3. **无 Swarm 子 Agent**：大任务无法拆解并行（`subagent.py` 有雏形未接循环）。
4. **无 Heartbeat**：不能定时自主复盘。

另：本会话 core 修复（`9decfdb`）**只在网页版生效，桌面装机版需重出 MSI**。

## User Stories

1. 作为用户，我希望发一条消息后**实时看到** Agent 的思考、每一步工具调用与结果，而不是干等最终答复。
2. 作为用户，我希望在对话框里让 Agent **真正写文件/生成代码**到工作区，而不是只把代码讲给我听。
3. 作为用户，我希望复杂任务能被**拆成子任务并行**执行并汇总成一份报告。
4. 作为产品方，我希望 Agent 能**定时自主复盘**推进未完成事项。
5. 作为桌面用户，我希望装机版也能用上最新修复（重出 MSI）。

## Implementation Decisions

### 契约（S2 先锁死，写进 CONTEXT.md）
- **事件三型**（对齐 OpenClaw，禁止别名）：
  - `lifecycle`：`{phase: "start"|"end"|"error", ...}`；
  - `tool`：`{event: "call"|"result", tool, args?, result?}`；
  - `assistant`：`{delta: "..."}`（流式文本增量）。
- **SSE 端点**：`POST /api/wb/chat/stream`（新增，不改现有 `/api/wb/chat` 契约，向后兼容）。事件 `data:` 为 JSON，`event:` 为三型之一。
- **工具执行唯一入口**：`agent_loop.run()` 内部经 `tools_registry.run_tool_governed()`（过 egress/HITL/熔断/审计）；**禁止**旁路。
- **写文件工具**：新增 `file.write`（`toolset="file"`, `requires_approval=True`），落盘前过 `core/security.py` 敏感路径黑名单 + 工作空间白名单；默认仅在 `allow_full_access=True` 时可用。
- **coding_agent 接入**：把 `coding_agent.generate_tool` 包成 `@tool("code.gen_tool", ..., requires_approval=True)`，进工具链。
- **Swarm**：`agent_loop` 内支持 `spawn_subagent(subtask)` → `agent_runtime` 隔离子会话 → `maxSpawnDepth=1`；主 Agent Fan-in 汇总。
- **Heartbeat**：`core/heartbeat.py` 定时（`scheduler.py` 复用）触发「复盘未完成任务」的 agent 会话。

### 兼容与红线
- 现有 `/api/wb/chat`（同步）**保持不变**，SSE 为新增路径；前端渐进切换。
- 不新增重依赖（SSE 用 FastAPI `StreamingResponse`，零新包）。
- 不触碰指纹文件 `agent.py`/`rag.py`/`db.py`（延续既有约束）。

## Testing Decisions

- 每票 Red-Green-Refactor：先写失败测试 → 最小实现 → 重构。
- **01 事件流**：`tests/_verify_event_stream.py`——断言 `agent_loop` 产出 `lifecycle/tool/assistant` 三型事件且顺序正确（start→tool:call→tool:result→assistant→end）；SSE 端点 `text/event-stream` + 逐帧可解析；接入 `verify.py` quick。
- **02 代码工具**：`tests/_verify_file_tools.py`——`file.write` 写白名单内成功、写黑名单/越权被拒、无审批不执行；`code.gen_tool` 走 HITL。
- **03 Swarm**：`tests/_verify_swarm.py`——拆分 3 子任务并行、`maxSpawnDepth` 生效、Fan-in 汇总含失败项。
- **04 Heartbeat**：`tests/_verify_heartbeat.py`——到点触发复盘、无任务不空跑。
- **S4 真实回归**：`run.py` 起服务 + huashu-chrome 真实浏览器，验证「发消息→看到流式思考/工具调用→最终答复」。
- 所有新测试接入 `scripts/verify.py` 闸门。

## Out-of-Scope（本 spec 不做）
- 前端 React 迁移（已决策不迁）。
- IM 通道（飞书/企微）接入（单独 spec）。
- 多租户 RBAC / 对外 HA（仅网页版对外部署形态需要）。
- 自动上下文 compaction（`memory_slim` 已有部分，单独评估）。

## Tracer-bullet 工单（按 frontier 顺序，详见 `issues/`）
| # | 票 | 依赖 | 状态 |
|---|---|---|---|
| 01 | 事件流 SSE（`agent_loop` emit + `/api/wb/chat/stream` + 前端流式渲染） | — | `ready-for-agent` |
| 02 | 代码/文件工具（`file.write` + `code.gen_tool`，HITL+白名单） | — | `ready-for-agent` |
| 03 | Swarm 子 Agent 并行（spawn + Fan-in + maxSpawnDepth） | 01 | `ready-for-agent` |
| 04 | Heartbeat 心跳自主复盘 | 01 | `ready-for-agent` |
| 05 | 桌面装机版重出 MSI（打包，非代码） | 01–04 视范围 | `ready-for-human` |
