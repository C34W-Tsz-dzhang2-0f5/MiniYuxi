"""Agent 编排：进程内轻量状态机（节点 + 条件分支 + 人工闸门 HITL）。

不依赖 LangGraph/任何外部服务——一个 dict 状态 + 一张节点表即可运行，
但保留了与 LangGraph 同构的语义（state / node / conditional edge / interrupt）。
后续要换 LangGraph，只需替换 run/step 两个函数，流程定义可原样复用。
"""
import json
import uuid
from datetime import datetime

from . import db
from .auth import new_id

# ---------------- 流程定义 ----------------
# 招聘 19 阶段：S2 / S9 / S13 为人工闸门（需人审批才继续）
RECRUIT_FLOW: dict[str, dict] = {
    "S1":  {"name": "需求提出", "hitl": False, "next": "S2"},
    "S2":  {"name": "需求审批", "hitl": True,  "next": "S3"},
    "S3":  {"name": "JD生成与发布", "hitl": False, "next": "S4"},
    "S4":  {"name": "简历收集", "hitl": False, "next": "S5"},
    "S5":  {"name": "AI初筛", "hitl": False, "next": "S6"},
    "S6":  {"name": "人才画像匹配", "hitl": False, "next": "S7"},
    "S7":  {"name": "HR电话初面", "hitl": False, "next": "S8"},
    "S8":  {"name": "面试安排", "hitl": False, "next": "S9"},
    "S9":  {"name": "用人部门面试与评价", "hitl": True, "next": "S10"},
    "S10": {"name": "复试/终面", "hitl": False, "next": "S11"},
    "S11": {"name": "背景调查", "hitl": False, "next": "S12"},
    "S12": {"name": "薪酬方案拟定", "hitl": False, "next": "S13"},
    "S13": {"name": "录用审批", "hitl": True,  "next": "S14"},
    "S14": {"name": "Offer发放", "hitl": False, "next": "S15"},
    "S15": {"name": "Offer确认与回签", "hitl": False, "next": "S16"},
    "S16": {"name": "入职材料准备", "hitl": False, "next": "S17"},
    "S17": {"name": "入职办理", "hitl": False, "next": "S18"},
    "S18": {"name": "试用期跟踪", "hitl": False, "next": "S19"},
    "S19": {"name": "转正评估与归档", "hitl": False, "next": None},
}

FLOWS = {"recruit": RECRUIT_FLOW}


def list_flows() -> dict:
    return {
        name: {
            "stages": len(nodes),
            "hitl": [k for k, v in nodes.items() if v["hitl"]],
            "entry": next(iter(nodes)),
        }
        for name, nodes in FLOWS.items()
    }


# ---------------- 运行时 ----------------
def _load(run_id: str) -> dict | None:
    row = db.connect().execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def _save(run_id: str, current: str, status: str, state: dict) -> None:
    db.connect().execute(
        "UPDATE agent_runs SET current=?, status=?, state_json=?, updated_at=? WHERE id=?",
        (current, status, json.dumps(state, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), run_id),
    )
    db.connect().commit()


def start(tenant_id: str, flow: str, init: dict | None = None) -> dict:
    if flow not in FLOWS:
        raise ValueError(f"未知流程：{flow}，可选：{list(FLOWS)}")
    run_id = new_id("run")
    entry = next(iter(FLOWS[flow]))
    state = {"flow": flow, "history": [], **({"data": init} if init else {})}
    db.connect().execute(
        "INSERT INTO agent_runs(id,tenant_id,flow,current,status,state_json) VALUES(?,?,?,?,?,?)",
        (run_id, tenant_id, flow, entry, "running", json.dumps(state, ensure_ascii=False)),
    )
    db.connect().commit()
    return {"run_id": run_id, "current": entry, "stage_name": FLOWS[flow][entry]["name"], "status": "running"}


def step(run_id: str, approve: bool = True, note: str = "") -> dict:
    """推进一步。遇人工闸门且未批准 → 停在 waiting。"""
    r = _load(run_id)
    if not r:
        raise ValueError("run 不存在")
    nodes = FLOWS[r["flow"]]
    cur = r["current"]
    state = json.loads(r["state_json"] or "{}")
    node = nodes[cur]

    if node["hitl"] and not approve:
        _save(run_id, cur, "waiting", state)
        return {"run_id": run_id, "current": cur, "stage_name": node["name"], "status": "waiting",
                "message": f"闸门 {cur}（{node['name']}）等待人工审批"}

    state.setdefault("history", []).append(
        {"stage": cur, "name": node["name"], "hitl": node["hitl"], "note": note,
         "at": datetime.now().isoformat(timespec="seconds")}
    )
    nxt = node["next"]
    if nxt is None:
        _save(run_id, cur, "done", state)
        return {"run_id": run_id, "current": cur, "stage_name": node["name"], "status": "done",
                "history": state["history"]}

    _save(run_id, nxt, "running", state)
    return {"run_id": run_id, "current": nxt, "stage_name": nodes[nxt]["name"], "status": "running",
            "hitl_next": nodes[nxt]["hitl"], "history": state["history"]}


def run_all(run_id: str, auto_approve: bool = True, max_steps: int = 100) -> dict:
    """连续推进直到完成/遇到未批准闸门。auto_approve=True 时自动通过闸门。"""
    for _ in range(max_steps):
        r = _load(run_id)
        state = json.loads(r["state_json"] or "{}")
        nodes = FLOWS[r["flow"]]
        cur = r["current"]
        res = step(run_id, approve=auto_approve, note="auto" if nodes[cur]["hitl"] else "")
        if res["status"] in {"done", "waiting"}:
            res["history"] = json.loads((_load(run_id)["state_json"] or "{}")).get("history", [])
            return res
    return {"run_id": run_id, "status": "max_steps_exceeded"}


def get_run(run_id: str) -> dict | None:
    r = _load(run_id)
    if not r:
        return None
    state = json.loads(r["state_json"] or "{}")
    return {"run_id": r["id"], "flow": r["flow"], "current": r["current"],
            "current_name": FLOWS[r["flow"]][r["current"]]["name"] if r["current"] else "",
            "status": r["status"], "history": state.get("history", [])}
