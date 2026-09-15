# -*- coding: utf-8 -*-
"""岗位任务流引擎（提示词 → 自动执行 端到端闭环）。

数据底座：skills/task_library.json（由 scripts/build_task_library.py 从 PDF 解析生成）。
职责：
  1. 加载任务库，按 role 列出任务目录；
  2. 把任一任务编译成 canvas 兼容 DAG（start→knowledge→llm→tool→approval→end）；
  3. 通过 orchestration.run_automation 跑通，全程写入 SOC 审计链；
  4. 输出结构化结果（材料核验 / 回答 / 建议追问 / 审计留痕）。

设计：零新增依赖；复用 gateway(LLM)、orchestration(canvas+审计)、db。
不触碰三指纹文件（db.py/rag.py/agent.py）。
"""
import json
import os

from . import db, gateway, orchestration, soc_audit, model_hub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_PATH = os.path.join(ROOT, "skills", "task_library.json")

ROLE_SYSTEM = {
    "admin_office": "你是一名资深的行政与综合办公专家，熟悉中国企业中的综合行政与办公支持，"
                    "输出需适合真实企业直接使用，结构清晰、可执行。",
    "hr": "你是一名资深的 HR／人力资源专家，熟悉中国企业中的人力资源全流程与劳动法合规口径，"
          "输出需给出可执行步骤、风险提示与制度依据。",
}


def init(conn=None):
    c = conn or db.connect()
    soc_audit.init(c)
    orchestration.init(c)
    try:
        model_hub.init(c)
    except Exception:
        pass
    return os.path.exists(LIB_PATH)


def _load():
    with open(LIB_PATH, encoding="utf-8") as f:
        return json.load(f)


def list_roles() -> list:
    d = _load()
    return [{"role": r, "role_line": m.get("role_line", ""), "count": m.get("count", 0)}
            for r, m in d.get("roles", {}).items()]


def list_tasks(role: str = None) -> list:
    d = _load()
    ts = d.get("tasks", [])
    if role:
        ts = [t for t in ts if t.get("role") == role]
    return [{"id": t["id"], "role": t["role"], "module": t["module"], "title": t["title"],
             "scenario": t["scenario"]} for t in ts]


def get_task(task_id: str) -> dict | None:
    for t in _load().get("tasks", []):
        if t["id"] == task_id:
            return t
    return None


def build_dag(task: dict) -> dict:
    """编译任务为 canvas 兼容 DAG（5 节点端到端闭环）。"""
    return {
        "name": f"{task['role']}/{task['title']}",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "materials", "type": "knowledge", "label": "读取并核验材料"},
            {"id": "exec", "type": "llm", "label": "执行主提示词"},
            {"id": "format", "type": "tool", "label": "套用输出格式"},
            {"id": "review", "type": "approval", "label": "人工确认闸门(HITL)"},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "materials"},
            {"from": "materials", "to": "exec"},
            {"from": "exec", "to": "format"},
            {"from": "format", "to": "review"},
            {"from": "review", "to": "end"},
        ],
    }


def get_workflow(task_id: str) -> dict | None:
    t = get_task(task_id)
    return build_dag(t) if t else None


def _fill_prompt(task: dict, variables: dict, materials: list) -> str:
    """把背景占位符（"企业/部门：[填写]" 形式）与材料清单注入主提示词。"""
    pt = task.get("prompt_template", "")
    subs = {
        "企业/部门": variables.get("dept", "（未填写，请据实补充）"),
        "本次目标": variables.get("goal", "（未填写）"),
        "使用对象": variables.get("audience", "（未填写）"),
        "时间范围与截止时间": variables.get("deadline", "（未填写）"),
    }
    for label, val in subs.items():
        pt = pt.replace(f"{label}：[填写]", f"{label}：{val}")
        pt = pt.replace(f"{label}:[填写]", f"{label}:{val}")
    mat_text = "\n".join(f"- {m}" for m in (materials or [])) or "（未提供附件，仅凭背景信息生成）"
    pt += f"\n\n【本次提供的材料清单】\n{mat_text}"
    return pt


def run_task(task_id: str, variables: dict = None, materials: list = None,
             tenant_id: str = "default", dry: bool = False, auto_approve: bool = True,
             model: str = None) -> dict:
    """端到端执行一个岗位任务。返回结构化结果 + 审计标记。"""
    task = get_task(task_id)
    if not task:
        return {"ok": False, "err": "task_not_found", "task_id": task_id}
    materials = materials or []
    variables = variables or {}
    dag = build_dag(task)
    system = ROLE_SYSTEM.get(task["role"], "你是一名资深企业专家。")
    filled = _fill_prompt(task, variables, materials)

    def h_start(node, g):
        return {"status": "started", "task_id": task_id}

    def h_knowledge(node, g):
        needed = task.get("inputs", [])
        provided = bool(materials)
        missing = needed if not provided else [
            i for i in needed if not any(i[:3] in p or p[:3] in i for p in materials)
        ]
        return {"provided": materials, "needed": needed,
                "missing": missing, "missing_count": len(missing),
                "note": "材料完整性核验完成；缺失项不得自行编造，已标注待补充"}

    def h_llm(node, g):
        if dry:
            return {"dry": True, "system": system, "prompt_preview": filled[:800]}
        if model:
            r = model_hub.chat(model, system, filled, tenant_id=tenant_id)
            return {"ok": r.get("ok"), "text": r.get("text", ""), "err": r.get("err"),
                    "model": r.get("model_id"), "model_name": r.get("model_name"),
                    "provider": r.get("provider"), "latency_ms": r.get("latency_ms"),
                    "tokens": r.get("tokens"), "cost": r.get("cost")}
        r = gateway.chat(system, filled, tenant_id=tenant_id)
        return {"ok": r.get("ok"), "text": r.get("text", ""), "err": r.get("err"),
                "model": r.get("model"), "provider": r.get("provider")}

    def h_format(node, g):
        llm_out = g.get("exec", {}).get("text", "")
        fmt = "\n".join(task.get("output_format", []))
        followups = "\n".join(f"- {f}" for f in task.get("followups", []))
        doc = (f"{llm_out}\n\n—— 输出格式要求（已套用）——\n{fmt}\n\n"
               f"—— 建议追问（可一键继续）——\n{followups}")
        return {"document": doc}

    def h_approval(node, g):
        if auto_approve:
            return {"approved": True, "mode": "auto"}
        return {"approved": False, "mode": "await_human", "note": "等待人工确认后放行"}

    def h_end(node, g):
        return {"final": g.get("format", {}).get("document", "")}

    handlers = {
        "start": h_start, "knowledge": h_knowledge, "llm": h_llm,
        "tool": h_format, "approval": h_approval, "end": h_end,
    }
    c = db.connect()
    init(c)
    res = orchestration.run_automation(dag, trigger="manual", ctx={"task_id": task_id},
                                        handlers=handlers, conn=c)
    out = res.get("outputs", {})
    answer = out.get("format", {}).get("document", "") if not dry else out.get("exec", {}).get("prompt_preview", "")
    return {
        "ok": res.get("ok"),
        "task_id": task_id,
        "role": task["role"],
        "title": task["title"],
        "module": task["module"],
        "materials_check": out.get("materials", {}),
        "answer": answer,
        "followups": task.get("followups", []),
        "audit": "已写入 SOC 审计链" if res.get("ok") else "未写入",
        "trace": {k: {kk: vv for kk, vv in v.items() if kk in ("status", "provided", "missing_count", "ok", "model", "model_name", "provider", "latency_ms", "tokens", "cost", "approved", "dry")} for k, v in out.items()},
    }
