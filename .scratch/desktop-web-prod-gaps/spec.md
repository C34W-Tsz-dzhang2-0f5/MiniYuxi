# Spec: 桌面版/网页版上生产线禁补齐（④ 可观测性 + ⑤ 成本硬熔断）

> 来源：`docs/enterprise-boundary-desktop-web-20260929.md` §3 门禁（🔴 必补项）
> 状态：`done`（两票均已于 2026-09-29 实现并接入 verify 闸门，commits 8825a49 / 29fa0ce / 058927d）
> 路由：`ask-matt` → multi-session build → 本 spec 由 `to-spec` 综合已知产出 → `to-tickets` 拆两票 → `implement` 每票 `/tdd` + `/code-review`

## Problem Statement

MiniYuxi 桌面版按席位商用，网页版可对外部署。当前 ③ 审计(SOC 哈希链)、⑥ HITL(审批卡) 已达标，但 **④ 可观测性完全缺失**（`grep` trace/span/metrics = 0 命中）、**⑤ 成本只有跟踪无硬熔断**（`usage.py` 记账但无预算上限/`maxSteps`/失控循环熔断）。这俩是桌面版上生产的硬门禁缺口：失控循环或成本爆雷即直接事故；网页对外缺 ④ 则无法定位问题。

## User Stories

1. 作为运维/开发者，我希望每次 Agent 运行有贯穿 `retrieval → tool call → action` 的 `trace_id` 与耗时/成本时间戳，以便在出问题时定位。
2. 作为商用产品方，我希望单次运行有 per-run/per-tenant/per-user 预算硬上限 + 步数上限 + 失控循环自动熔断+告警，以便成本可控、不爆雷。
3. 作为网页版部署方，我希望可观测指标可导出（成功率/延迟/单次成本/升级率），以便监控面板接入。

## Implementation Decisions

- **④ 可观测性**：在 `core/` 调用链注入 `trace_id`（贯穿 `agent_loop` / `gateway` / `tools_registry` / `egress` / `approval`），落结构化 span 到 `soc_audit` 或独立 tracing 表；导出指标（成功率/延迟/单次成本/升级率）。**不引入新重依赖**（延续零依赖原则，复用 `db.connect()`）。
- **⑤ 成本硬熔断**：在 `core/agent_runtime.py` 或 `agent_loop.py` 加预算闸门——`maxSteps` / `timeoutMs` / `maxTokensPerRun` / per-tenant|user 预算；超限即熔断 + 告警（接 `usage.py` 的记账）。失控循环检测（步数/重复动作）触发 `approval` 升级或终止。
- 两票均为**全栈纵向切片**：core 改动 → API 暴露 → （网页版）`web/` 指标面板可选 → 测试，可独立验证。

## Testing Decisions

- ④：加 `_verify_observability.py`——注入 `trace_id` 贯穿断言（retrieval/tool/action 同 id）、指标导出断言；接入 `scripts/verify.py` 闸门。
- ⑤：加 `_verify_cost_circuit_breaker.py`——超步数/超预算/失控循环三个熔断用例（Red-Green-Refactor，先写失败测试）。
- 真实回归：`run.py`(8801) 起服务，跑一个会失控的对话，验证熔断生效（S4 HTTP 级 e2e；可选 playwright 真实浏览器）。

## Out-of-Scope（本 spec 不做）

- ① 多租户数据层隔离（仅网页版对外部署形态需要，本 spec 不触数据层）。
- ② 网页版 RBAC（单独 spec）。
- ⑧ canary（桌面版无 canary，回滚=重装旧 MSI）。
- 等保/ISO/CMK/HA 的外部认证与基础设施（非代码范畴，见 ADR-0001）。
