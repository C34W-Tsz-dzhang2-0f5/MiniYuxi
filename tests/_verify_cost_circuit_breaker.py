"""验证 ⑤ 成本硬熔断：步数 / 超时 / token / 成本 / 租户预算 / 失控循环 六个触发条件。

纯逻辑，离线可跑，不依赖 LLM。
跑法：python tests/_verify_cost_circuit_breaker.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import circuit_breaker  # noqa: E402
import core.usage as usage_mod  # noqa: E402

FAIL = []


def check(cond, msg):
    if cond:
        print("[PASS]", msg)
    else:
        print("[FAIL]", msg)
        FAIL.append(msg)


# 步数上限
g = circuit_breaker.BudgetGuard(max_steps=3)
r1, r2, r3, r4 = g.check_step(), g.check_step(), g.check_step(), g.check_step()
check(r1[0] == "closed" and r2[0] == "closed" and r3[0] == "closed", "步数未达上限→closed")
check(r4[0] == "open" and r4[1] == "max_steps", "步数超限→open(max_steps)")

# token 上限
g = circuit_breaker.BudgetGuard(max_tokens=100)
g.record_tokens(60)
a = g.check_step()
check(a[0] == "closed", "token 未超限→closed")
g.record_tokens(60)
b = g.check_step()
check(b[0] == "open" and b[1] == "max_tokens", "token 超限→open(max_tokens)")

# 成本上限
g = circuit_breaker.BudgetGuard(max_cost=0.5)
g.record_cost(0.3)
a = g.check_step()
check(a[0] == "closed", "成本未超限→closed")
g.record_cost(0.3)
b = g.check_step()
check(b[0] == "open" and b[1] == "max_cost", "成本超限→open(max_cost)")

# 超时
g = circuit_breaker.BudgetGuard(timeout_ms=5)
time.sleep(0.02)
a = g.check_step()
check(a[0] == "open" and a[1] == "timeout", "超时→open(timeout)")

# 失控循环（连续相同动作）
g = circuit_breaker.BudgetGuard(runaway_limit=3)
check(g.check_step(action_key="kb.search")[0] == "closed", "重复1次→closed")
check(g.check_step(action_key="kb.search")[0] == "closed", "重复2次→closed")
check(g.check_step(action_key="kb.search")[0] == "closed", "重复3次→closed")
d4 = g.check_step(action_key="kb.search")
check(d4[0] == "open" and "runaway" in d4[1], "连续4次相同动作→open(runaway)")
# 切换动作重置计数（不误判）
g2 = circuit_breaker.BudgetGuard(runaway_limit=3)
g2.check_step(action_key="a")
g2.check_step(action_key="b")
g2.check_step(action_key="a")
check(g2.check_step(action_key="a")[0] == "closed", "切换动作后不误判失控")

# 租户累计预算（mock usage.stats）
orig = usage_mod.stats
usage_mod.stats = lambda tid: {"total": {"cost": 9.9, "prompt_tokens": 0, "completion_tokens": 0, "calls": 5}}
g = circuit_breaker.BudgetGuard(tenant_id="t1", tenant_budget=5.0)
check(g.check_step()[0] == "open" and g.check_step()[1] == "tenant_budget", "租户累计成本超限→open")
usage_mod.stats = orig

if FAIL:
    print("CIRCUIT BREAKER VERIFY FAILED:", len(FAIL))
    sys.exit(1)
print("CIRCUIT BREAKER VERIFY ALL PASS")
