# MiniYuxi 路线图（ROADMAP）

> 本路线图基于仓库内 `.scratch/agent-runtime-upgrade/spec.md` 与已落地提交整理，状态截至 2026-10-22。
> 规划项可能随交付优先级调整；进行中的票以 `.scratch/agent-runtime-upgrade/issues/` 中的工单为准。

## ✅ 已完成

| 能力 | 说明 | 证据 |
|---|---|---|
| 三端统一内核 | Web(SPA) / Desktop(Tauri sidecar) / CLI 共用 `core/` | v0.2.2 Release《三端统一 P3 桌面端落地》 |
| 事件流 SSE | `agent_loop` emit 三型事件（lifecycle / tool / assistant）+ `/api/wb/chat/stream` + 前端流式渲染，向后兼容旧契约 | 20 项断言验证，接入 verify 闸门 |
| 多 Provider 故障转移 | `provider_router.chat_with_tools()`：出境闸门 → 瞬断重试 → 按优先级切供应商 → 离线兜底 | 17 例测试 |
| 成本硬熔断 | BudgetGuard：步数 / 超时 / token / 成本 / 租户预算 / 失控循环六类触发 | 13 项断言 |
| 可观测性 | trace_id + span 落库 + 指标导出，失败不阻断主链路 | 10 项断言 |
| 模型 Key 界面化 | 6 家供应商预设增改删 + 保存前验活 + 脱敏返回（has_key 替代明文） | 12 项测试 |
| 对话内安装/卸载技能 | `npx skills add` 确定性快路径 + git clone 镜像兜底 + 集合仓库挑技能 | 65 项自检 + e2e |

## 🚧 进行中（工单已定义，见 `.scratch/agent-runtime-upgrade/issues/`）

| # | 能力 | 目标 | 状态 |
|---|---|---|---|
| 02 | 代码 / 文件工具 | `file.write`（HITL + 工作空间白名单 + 敏感路径黑名单）+ `code.gen_tool` 接入工具链 | 契约已锁（spec.md），待实现 |
| 03 | Swarm 子 Agent | `spawn_subagent(subtask)` 隔离子会话 + `maxSpawnDepth=1` + Fan-in 汇总 | 依赖 01（已就绪） |
| 04 | Heartbeat | 定时触发「复盘未完成任务」的 agent 会话，无任务不空跑 | 依赖 01（已就绪） |

## 📋 计划中

| 事项 | 说明 | 前置条件 |
|---|---|---|
| 桌面装机版 MSI 0.4.0 重发 | 网页版 core 修复需重新打包才能惠及装机版 | 需装有 WiX Toolset v3 的 Windows 主机（工单 05，`ready-for-human`） |
| 前端场景技能卡 | 不迁 React，按 spec 决策只补 SSE 事件流 + 场景技能卡 | 01 已就绪 |
| 多语言 README | 英文版已有（`README_en.md`），持续同步 | — |

## 💡 探索中（未排期）

- IM 通道接入（飞书 / 企微）——单独 spec，Out-of-Scope 于当前运行时升级
- 自动上下文 compaction（`memory_slim` 已有部分能力，需单独评估）
- 多租户 RBAC / 对外 HA 部署形态（当前定位单租户桌面优先）

---

> 想要参与？见 [CONTRIBUTING.md](CONTRIBUTING.md)；提交前请跑 `python scripts/verify.py`。
