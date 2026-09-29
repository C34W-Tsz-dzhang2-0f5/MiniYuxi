# 02 · 成本硬熔断（maxSteps / 预算上限 / 失控循环）

- **Status:** open
- **Type:** task
- **Blocked by:** （无，可立即开工；与 01 无依赖）
- **Feature:** desktop-web-prod-gaps
- **Source spec:** `.scratch/desktop-web-prod-gaps/spec.md` §Implementation Decisions ⑤

## 纵向切片（tracer bullet）

在运行入口（`core/agent_runtime.py` 或 `agent_loop.py`）加预算闸门：`maxSteps` / `timeoutMs` / `maxTokensPerRun` / per-tenant|user 预算上限；超限即熔断 + 告警；失控循环检测（步数/重复动作）触发 `approval` 升级或终止。复用 `usage.py` 记账。

## 验收

- [ ] 超步数 / 超预算 / 失控循环 三场景均被熔断（不无限循环、不产生超额 token）
- [ ] 熔断有告警（日志/SOC 链）
- [ ] `_verify_cost_circuit_breaker.py` 新增并接入 `scripts/verify.py` 闸门
- [ ] 配置项（上限数值）可经 `core/config.py` 读取，不硬编码

## Comments
（空）
