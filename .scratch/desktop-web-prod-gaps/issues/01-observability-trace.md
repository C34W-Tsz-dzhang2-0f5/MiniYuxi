# 01 · 可观测性 trace_id 贯穿 + 指标导出

- **Status:** open
- **Type:** task
- **Blocked by:** （无，可立即开工）
- **Feature:** desktop-web-prod-gaps
- **Source spec:** `.scratch/desktop-web-prod-gaps/spec.md` §Implementation Decisions ④

## 纵向切片（tracer bullet）

贯穿 `agent_loop` → `gateway`/`model_hub`/`provider_router` → `tools_registry` → `egress`/`approval` 的 `trace_id` 注入 + 耗时/成本时间戳；落结构化 span（复用 `db.connect()`，零新依赖）；导出指标（成功率/延迟/单次成本/升级率）。

## 验收

- [ ] 一次对话的 retrieval/tool/action 记录共享同一 `trace_id`
- [ ] 指标可查询/导出（JSON 或端点）
- [ ] `_verify_observability.py` 新增并接入 `scripts/verify.py` 闸门（全量 6/6→7/7 绿）
- [ ] 命名严格对齐 `CONTEXT.md`（用 `trace_id`/`observability`，不用 `span_id`/`monitor` 等别名）

## Comments
（空）
