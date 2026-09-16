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
import re
import subprocess
import sys
from datetime import datetime

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
    if task.get("kind") == "skill":
        resume_path = materials[0] if (materials and materials[0]) else None
        role_name = (variables or {}).get("role_name")
        return run_skill_task(task_id, resume_path=resume_path, role_name=role_name,
                             tenant_id=tenant_id, dry=dry, auto_approve=auto_approve, model=model)
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


def run_skill_task(task_id: str, *, resume_path: str = None, role_name: str = None,
                   tenant_id: str = "default", dry: bool = False, auto_approve: bool = True,
                   model: str = None) -> dict:
    """执行 kind=skill 的任务（如 hr_resume 简历筛选）。

    链路（复用 build_dag 的 6 节点结构）：
      knowledge 定位/读取简历 → llm(DeepSeek) 提取结构化候选人 + 按标准逐项打分 →
      tool 调 skills/<skill>/scripts/pipeline.py 做确定性加权评分并写入 candidates.csv →
      approval(HITL) → end 返回报告与 CSV 路径。
    确定性评分引擎为纯标准库 Python，可离线运行、可审计；LLM 只做「标准化提取」。
    """
    task = get_task(task_id)
    if not task or task.get("kind") != "skill":
        return {"ok": False, "err": "not_skill_task", "task_id": task_id}

    skill = task.get("skill", "")
    skill_dir = os.path.join(ROOT, "skills", skill)
    scripts_dir = os.path.join(skill_dir, "scripts")
    std_dir = os.path.join(skill_dir, "scoring_standards")
    inbox_dir = os.path.join(skill_dir, "inbox")
    data_dir = os.path.join(skill_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    dag = build_dag(task)  # 复用相同 6 节点结构（type 映射一致）
    role = role_name or task.get("skill_role")

    def _match_standard(rn):
        if not rn or not os.path.isdir(std_dir):
            return None, None
        for p in sorted(os.listdir(std_dir)):
            if p.startswith("_") or not p.endswith(".json"):
                continue
            try:
                d = json.loads(open(os.path.join(std_dir, p), encoding="utf-8").read())
            except Exception:
                continue
            if d.get("role") == rn:
                return os.path.join(std_dir, p), d
        return None, None

    def _extract_json(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            m = re.search(r"\{.*\}", s, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return None
        return None

    def h_start(node, g):
        return {"status": "started", "task_id": task_id, "skill": skill}

    def h_knowledge(node, g):
        path = None
        if resume_path and os.path.isfile(resume_path):
            path = resume_path
        elif os.path.isdir(inbox_dir):
            files = sorted(f for f in (os.path.join(inbox_dir, f) for f in os.listdir(inbox_dir))
                           if os.path.isfile(f) and not os.path.basename(f).startswith("_"))
            if files:
                path = files[0]
        text = ""
        if path:
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except Exception:
                text = ""
        return {"resume_path": path, "resume_text": text[:6000], "chars": len(text),
                "note": "已读取简历；缺失项不得编造"}

    def h_llm(node, g):
        resume_text = g.get("materials", {}).get("resume_text", "")
        std_path, std = _match_standard(role)
        if not std:  # 兜底：取第一个非模板标准
            for p in sorted(os.listdir(std_dir)):
                if p.startswith("_") or not p.endswith(".json"):
                    continue
                try:
                    d = json.loads(open(os.path.join(std_dir, p), encoding="utf-8").read())
                except Exception:
                    continue
                std_path, std = os.path.join(std_dir, p), d
                break
        dims = std.get("scoring", {}).get("dimensions", []) if std else []
        dim_desc = "\n".join(
            f"- {d['key']}（{d['name']}，权重 {d.get('weight')}，满分 {d.get('max', 10)}）: {d.get('description', '')}"
            for d in dims
        )
        prompt = (
            (task.get("prompt_template", "") or "") + "\n\n# 简历内容\n" + resume_text + "\n\n"
            "# 评分标准（岗位：" + (std.get("role", "未知") if std else "未知") + "）\n" + dim_desc + "\n\n"
            "请严格按上述维度为候选人逐项打分（1-10 整数），并只输出如下 JSON（不要任何额外文字）：\n"
            '{"姓名":"","性别":"","年龄":0,"手机号":"","邮箱":"","求职意向岗位":"",'
            '"毕业院校":"","学历层次":"","专业名称":"","是否985/211":"","工作年限":0,"是否大厂背景":"",'
            '"工作经历摘要":"","技能清单":"",'
            '"dim_scores":{"education_match":0,"experience_relevance":0,"skill_fit":0,"project_depth":0,"stability":0,"potential":0},'
            '"总结评价":"","建议问题":""}'
        )
        if dry:
            return {"dry": True, "prompt_preview": prompt[:800], "std_role": std.get("role") if std else None}
        if model:
            r = model_hub.chat(model, "你是资深简历解析与评分助手，只输出结构化 JSON，不要解释。", prompt, tenant_id=tenant_id)
        else:
            r = gateway.chat("你是资深简历解析与评分助手，只输出结构化 JSON，不要解释。", prompt, tenant_id=tenant_id)
        return {"ok": r.get("ok"), "raw": r.get("text", ""), "candidate": _extract_json(r.get("text", "")),
                "model": r.get("model") or r.get("model_id"), "provider": r.get("provider"),
                "std_path": std_path, "std_role": std.get("role") if std else None,
                "latency_ms": r.get("latency_ms"), "tokens": r.get("tokens"), "cost": r.get("cost")}

    def h_tool(node, g):
        if dry:
            return {"status": "dry", "note": "dry 模式不写库"}
        llm = g.get("exec", {})
        cand = llm.get("candidate")
        std_path = llm.get("std_path")
        resume_text = g.get("materials", {}).get("resume_text", "")

        # 规则引擎双轨：确定性评分（离线可用，作交叉校验 / DeepSeek 不可用时的降级）
        rule = None
        try:
            from core import resume_screening as rs
            rule = rs.screen_resume(resume_text, role or "", None)
        except Exception:
            rule = None

        if not cand or not std_path or not os.path.isfile(std_path):
            # LLM 失败 → 规则引擎离线降级（确定性、可审计）
            if rule:
                return {"status": "rule_fallback",
                        "rule_bucket": rule.get("bucket"), "rule_score": rule.get("score"),
                        "rule_hard_pass": rule.get("hard_pass"),
                        "rule_fields": rule.get("fields"),
                        "note": "DeepSeek 未产出有效结果，已用规则引擎离线降级评分（确定性、可审计；"
                                "未写入 candidates.csv，需人工复核）"}
            return {"status": "no_candidate", "note": "LLM 未产出有效候选人 JSON 或找不到评分标准",
                    "raw_llm": (llm.get("raw", "") or "")[:500]}
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cand_path = os.path.join(data_dir, f"_cand_{ts}.json")
        open(cand_path, "w", encoding="utf-8").write(json.dumps(cand, ensure_ascii=False, indent=2))
        py = os.path.join(scripts_dir, "pipeline.py")
        try:
            add_out = subprocess.run([sys.executable, py, "add", "--standard", std_path,
                                      "--candidate", cand_path], capture_output=True, text=True,
                                     cwd=skill_dir, timeout=120)
            rep_out = subprocess.run([sys.executable, py, "report", "--min", "8"],
                                     capture_output=True, text=True, cwd=skill_dir, timeout=120)
            cross = ""
            if rule:
                cross = (f"\n\n—— 规则引擎交叉校验（离线降级通道）——\n"
                         f"三档：{rule.get('bucket')} | 规则总分：{rule.get('score')} | "
                         f"硬条件通过：{rule.get('hard_pass')}\n"
                         f"解析字段：{json.dumps(rule.get('fields', {}), ensure_ascii=False)}")
            return {"status": "done",
                    "add_stdout": (add_out.stdout or add_out.stderr).strip(),
                    "report_stdout": (rep_out.stdout or rep_out.stderr).strip() + cross,
                    "csv_path": os.path.join(data_dir, "candidates.csv"),
                    "candidate_json": cand_path,
                    "rule": {"bucket": rule.get("bucket"), "score": rule.get("score")} if rule else None,
                    "note": "确定性评分已写入 candidates.csv（纯标准库引擎，可离线审计）；规则引擎已作交叉校验"}
        except Exception as e:
            return {"status": "error", "err": str(e)}

    def h_approval(node, g):
        if auto_approve:
            return {"approved": True, "mode": "auto"}
        return {"approved": False, "mode": "await_human", "note": "等待人工确认后放行"}

    def h_end(node, g):
        tool = g.get("format", {})
        cand = g.get("exec", {}).get("candidate") or {}
        # 脱敏：手机号/邮箱在返回结果中掩码，避免明文泄露
        try:
            from core import security as sec
            if cand.get("手机号"):
                cand = dict(cand)
                cand["手机号"] = sec.mask_phone(str(cand["手机号"]))
            if cand.get("邮箱"):
                cand = dict(cand)
                cand["邮箱"] = sec.mask_email(str(cand["邮箱"]))
        except Exception:
            pass
        return {"report": tool.get("report_stdout", ""), "csv_path": tool.get("csv_path"),
                "add_log": tool.get("add_stdout", ""), "candidate_json": tool.get("candidate_json"),
                "rule": tool.get("rule"), "candidate_masked": cand}

    handlers = {
        "start": h_start, "knowledge": h_knowledge, "llm": h_llm,
        "tool": h_tool, "approval": h_approval, "end": h_end,
    }
    c = db.connect()
    init(c)
    res = orchestration.run_automation(dag, trigger="manual", ctx={"task_id": task_id, "kind": "skill"},
                                        handlers=handlers, conn=c)
    out = res.get("outputs", {})
    tool_out = out.get("format", {})
    return {
        "ok": res.get("ok"),
        "task_id": task_id,
        "kind": "skill",
        "skill": skill,
        "role": task.get("role"),
        "title": task.get("title"),
        "resume_path": out.get("materials", {}).get("resume_path"),
        "std_role": out.get("exec", {}).get("std_role"),
        "model": out.get("exec", {}).get("model"),
        "provider": out.get("exec", {}).get("provider"),
        "candidate": out.get("exec", {}).get("candidate"),
        "report": tool_out.get("report_stdout"),
        "csv_path": tool_out.get("csv_path"),
        "add_log": tool_out.get("add_stdout"),
        "rule": tool_out.get("rule"),
        "candidate_masked": tool_out.get("candidate_masked"),
        "audit": "已写入 SOC 审计链" if res.get("ok") else "未写入",
        "trace": {k: {kk: vv for kk, vv in v.items() if kk in ("status", "chars", "ok", "model", "provider", "std_role", "approved", "dry", "note")} for k, v in out.items()},
    }
