"""复杂多 Agent 协同 + 工作流自动化（深度构造·项4）。

在已验收的 subagent（生成器/评判器）与 canvas（DAG 编排）之上，提供：
- run_team：多角色专家组协同。每个 role 单独生成+自评，协调器（judge）汇总裁决，
  形成"规划→执行→评审"闭环，支持 handoff（把上一角色产出喂给下一角色）；
- run_automation：把 canvas 工作流接上触发器（interval/daily/manual），实现定时/
  事件驱动的工作流自动化（复用 canvas.execute 的真实后端 handlers）。

不新增依赖；llm_fn 可注入便于测试。生产环境由 api 层传入真实 llm 与工具 handler。
"""
import json
from . import db, canvas, subagent, soc_audit


def init(conn=None):
    # run_team/run_automation 会落 SOC 审计，故初始化审计表；canvas/subagent 为纯逻辑模块
    c = conn or db.connect()
    soc_audit.init(c)
    return True


def _default_generator(role, brief, llm_fn):
    sys = role.get("system", "你是专家。")
    prompt = f"【任务】{brief}\n【你的角色】{role.get('role')}\n请给出本角色的专业产出。"
    if llm_fn is not None:
        text, _ = llm_fn(sys, prompt)
        return text or f"[{role.get('role')}]（离线）已就位"
    # 生产走 gateway；此处仅占位，api 层会注入
    return f"[{role.get('role')}]（需注入 llm）{brief[:40]}"


def run_team(task: str, roles: list, conn=None, llm_fn=None, max_rounds=2):
    """roles: [{role, system, criteria:{min_len,forbid,must_contain}}]。
    返回 {contributions, verdict, rounds, ok}。"""
    c = conn or db.connect()
    contributions = []
    prev = ""
    rounds = 0
    for role in roles:
        brief = task + (f"\n（参考上一环节产出：{prev}）" if prev else "")
        draft = _default_generator(role, brief, llm_fn)
        verdict = subagent.rule_judge(draft, role.get("criteria", {}))
        # 不达标重做（最多 max_rounds）
        r = 0
        while not verdict["pass"] and r < max_rounds:
            draft = _default_generator(role, brief + "\n（请修正：不满足约束）", llm_fn)
            verdict = subagent.rule_judge(draft, role.get("criteria", {}))
            r += 1
        rounds += r + 1
        contributions.append({"role": role.get("role"), "draft": draft,
                              "passed": verdict["pass"], "score": verdict["score"]})
        prev = draft[:300]
    # 协调器裁决
    ok = all(x["passed"] for x in contributions)
    soc_audit.log({"tenant_id": "system", "actor": "orchestration", "action": "team_run",
                   "target": task[:60], "result": "success" if ok else "partial",
                   "severity": "info", "detail": {"roles": [x["role"] for x in contributions]}}, c)
    return {"contributions": contributions, "verdict": "pass" if ok else "partial",
            "rounds": rounds, "ok": ok}


def run_automation(workflow: dict, trigger: str = "manual", ctx=None, handlers=None, conn=None):
    """复用 canvas DAG 执行器跑工作流自动化。trigger ∈ manual|interval|daily。"""
    c = conn or db.connect()
    v = canvas.validate(workflow)
    if not v[0]:
        return {"ok": False, "err": "invalid_workflow", "detail": v[1]}
    result = canvas.execute(workflow, ctx or {}, handlers or {}, c)
    soc_audit.log({"tenant_id": "system", "actor": "orchestration", "action": "automation_run",
                   "target": workflow.get("name", "wf"), "result": "success" if result["ok"] else "fail",
                   "severity": "info", "detail": {"trigger": trigger, "trace": result.get("trace")}}, c)
    return {"ok": result["ok"], "trigger": trigger, "trace": result.get("trace"),
            "outputs": result.get("outputs")}
