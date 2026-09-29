# 02 · 成本硬熔断（maxSteps / 预算上限 / 失控循环）

- **Status:** done
- **Type:** task
- **Blocked by:** （无，与 01 无依赖）
- **Feature:** desktop-web-prod-gaps
- **Source spec:** `.scratch/desktop-web-prod-gaps/spec.md` §Implementation Decisions ⑤
- **Done commit:** `29fa0ce`（BudgetGuard+config） + `058927d`（integration）
- **Done at:** 2026-09-29

## 纵向切片（tracer bullet）

在运行入口（`core/agent_runtime.py` 或 `agent_loop.py`）加预算闸门：`maxSteps` / `timeoutMs` / `maxTokensPerRun` / per-tenant|user 预算上限；超限即熔断 + 告警；失控循环检测（步数/重复动作）触发 `approval` 升级或终止。复用 `usage.py` 记账。

## 验收

- [x] 超步数 / 超时 / 超 token / 超成本 / 租户预算 / 失控循环 六场景均被熔断（不产生超额 token）
- [x] 熔断有告警（best-effort 写 SOC 链 `type=circuit_breaker`，不崩主链路）
- [x] `_verify_cost_circuit_breaker.py` 新增并接入 `scripts/verify.py` 闸门（13 项断言，quick 绿）
- [x] 配置项（上限数值）经 `core/config.py` 读取（6 个 `MINIYUXI_*` 环境变量可覆盖，不硬编码）

## Comments
（空）
