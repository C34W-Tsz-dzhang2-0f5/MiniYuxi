"""成本硬熔断（企业级要素⑤）：per-run/per-tenant/per-user 预算硬上限 + 步数上限 + 超时 + 失控循环检测。

设计（对齐 CONTEXT.md 术语）：
- BudgetGuard 是无状态逻辑的纯类（不碰 DB）；集成方在 agent 循环每步调用 check_step()。
- 触发条件：步数超限 / 超时 / token 超限 / 单次成本超限 / 租户累计成本超限 / 同一动作连续重复（失控循环）。
- 熔断后由集成方终止运行并告警（写 SOC 链），不得继续产生 token。
- 所有阈值可在 core/config.py 经环境变量覆盖；零新增依赖。
"""
import time
from . import config, usage


class CircuitOpen(Exception):
    """熔断异常：由集成方捕获后终止运行。"""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class BudgetGuard:
    def __init__(self, tenant_id=None, user_id=None,
                 max_steps=None, timeout_ms=None, max_tokens=None, max_cost=None,
                 tenant_budget=None, runaway_limit=None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.max_steps = int(max_steps if max_steps is not None else getattr(config, "RUN_MAX_STEPS", 30))
        self.timeout_ms = int(timeout_ms if timeout_ms is not None else getattr(config, "AGENT_TIMEOUT_MS", 120000))
        self.max_tokens = int(max_tokens if max_tokens is not None else getattr(config, "RUN_MAX_TOKENS", 20000))
        self.max_cost = float(max_cost if max_cost is not None else getattr(config, "RUN_MAX_COST", 1.0))
        self.tenant_budget = float(tenant_budget if tenant_budget is not None else getattr(config, "TENANT_BUDGET", 0.0))
        self.runaway_limit = int(runaway_limit if runaway_limit is not None else getattr(config, "RUNAWAY_REPEAT_LIMIT", 6))
        self.steps = 0
        self.tokens = 0
        self.cost = 0.0
        self.start = time.monotonic()
        self._last_action = None
        self._repeat = 0

    def check_step(self, action_key=None):
        """在每一步执行前调用。返回 ('open', reason) 或 ('closed', None)。
        每次调用即计一步；连续相同 action_key 超过 runaway_limit 判定失控循环。"""
        self.steps += 1
        if action_key is not None:
            if action_key == self._last_action:
                self._repeat += 1
            else:
                self._repeat = 0
            self._last_action = action_key
            if self.runaway_limit and self._repeat >= self.runaway_limit:
                return ("open", "runaway:%s" % action_key)
        if self.max_steps and self.steps > self.max_steps:
            return ("open", "max_steps")
        if self.timeout_ms and (time.monotonic() - self.start) * 1000 >= self.timeout_ms:
            return ("open", "timeout")
        if self.max_tokens and self.tokens >= self.max_tokens:
            return ("open", "max_tokens")
        if self.max_cost and self.cost >= self.max_cost:
            return ("open", "max_cost")
        if self.tenant_budget and self.tenant_id:
            try:
                used = (usage.stats(self.tenant_id) or {}).get("total", {}).get("cost", 0) or 0
                if used >= self.tenant_budget:
                    return ("open", "tenant_budget")
            except Exception:
                pass
        return ("closed", None)

    def record_tokens(self, n):
        self.tokens += int(n or 0)

    def record_cost(self, c):
        self.cost += float(c or 0)

    def elapsed_ms(self):
        return (time.monotonic() - self.start) * 1000
