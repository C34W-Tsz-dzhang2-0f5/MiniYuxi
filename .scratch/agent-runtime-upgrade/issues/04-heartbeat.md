# 04 · Heartbeat 心跳自主复盘

Status: `ready-for-agent`
Depends on: 01（事件流）
Owner: —

## 目标
无用户消息时，Agent 定时**自主复盘 / 自检 / 推进**未完成任务。对标 OpenClaw `HEARTBEAT.md` + 心跳循环。

## 契约
- 新增 `core/heartbeat.py`：`tick()` 检查「有无待推进任务」，有则触发一轮 agent 会话（复用 `agent_runtime`），无则空跑返回（**不空烧 token**）。
- 复用 `core/scheduler.py` 定时驱动（不引入新调度器）。
- 复盘结果写入 `soc_audit`（可追溯）+ 落「待办」表供下次 tick 续。
- 默认**关闭**，经配置开关 `MINIYUXI_HEARTBEAT=1` 启用（避免默认空跑耗成本）。

## 验收（先写失败测试）
- [ ] `tests/_verify_heartbeat.py`：到点触发复盘 / 无任务不空跑（0 次 LLM 调用）/ 结果入 SOC 链。
- [ ] 默认关闭时零副作用。
- [ ] 接入 `scripts/verify.py`。

## Done
- commit: _（实现后填）_
