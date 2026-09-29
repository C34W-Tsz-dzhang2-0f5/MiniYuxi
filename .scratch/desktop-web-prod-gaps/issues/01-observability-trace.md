# 01 · 可观测性 trace_id 贯穿 + 指标导出

- **Status:** done
- **Type:** task
- **Blocked by:** （无）
- **Feature:** desktop-web-prod-gaps
- **Source spec:** `.scratch/desktop-web-prod-gaps/spec.md` §Implementation Decisions ④
- **Done commit:** `8825a49` + `058927d`（integration）
- **Done at:** 2026-09-29

## 纵向切片（tracer bullet）

贯穿 `agent_loop` → `gateway`/`model_hub`/`provider_router` → `tools_registry` → `egress`/`approval` 的 `trace_id` 注入 + 耗时/成本时间戳；落结构化 span（复用 `db.connect()`，零新依赖）；导出指标（成功率/延迟/单次成本/升级率）。

## 验收

- [x] 一次对话的 retrieval/tool/action 记录共享同一 `trace_id`（observability.start_trace + span 贯穿）
- [x] 指标可查询/导出（`get_metrics()` 返回 dict：成功率/延迟/成本/by_span 聚合）
- [x] `_verify_observability.py` 新增并接入 `scripts/verify.py` 闸门（quick 子集 6/6 绿，含本卡点）
- [x] 命名严格对齐 `CONTEXT.md`（用 `trace_id`/`observability`，不用 `span_id`/`monitor` 等别名）

## Comments
（空）
