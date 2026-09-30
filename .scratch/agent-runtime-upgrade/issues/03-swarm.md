# 03 · Swarm 子 Agent 并行（spawn + Fan-in + maxSpawnDepth）

Status: `ready-for-agent`
Depends on: 01（事件流，子 Agent 需 emit 事件）
Owner: —

## 目标
主 Agent 把大任务拆成子任务，**派生隔离子会话并行执行**，Fan-in 汇总。对标 OpenClaw `spawnSubAgents`。

## 契约
- 新增 `@tool("agent.spawn", ..., toolset="swarm")`：入参 `{subtasks: [str]}`，返回各子任务结果。
- 复用 `core/subagent.py` + `core/agent_runtime.py`（`create` 独立 session_id，隔离 workspace）。
- `maxSpawnDepth=1`：子 Agent **不得**再派生孙 Agent（防 Agent 风暴）。
- 子 Agent 并发经**独立 lane**（不占主会话 lane），默认并发上限 8。
- **权限冒泡**：子 Agent 遇 `requires_approval` 工具 → 暂停并向上主 Agent 申请审批（接 `approval`）。
- 容错：单子 Agent 超时熔断不阻塞其余；Fan-in 收集全部（含失败项），主 Agent 决定重试或标注。

## 验收（先写失败测试）
- [ ] `tests/_verify_swarm.py`：拆分 3 子任务并行执行 / `maxSpawnDepth` 生效（孙 Agent 被拒）/ Fan-in 汇总含失败项。
- [ ] 子 Agent 工具调用过 egress/HITL/审计（不旁路）。
- [ ] 接入 `scripts/verify.py`。
- [ ] S4：真实浏览器发「全维度评估 X」→ 看到多子 Agent 事件 → 汇总报告。

## Done
- commit: _（实现后填）_
