"""MiniYuxi 平台 API：多租户 + RBAC + 知识库 + Agent 编排 + 审计。

单进程 FastAPI，挂载静态前端，原生 `uvicorn` 直接跑，无容器无外部依赖。
"""
import json
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import agent, auth, config, db, rag
import core.gateway as gateway
import core.usage as usage
import core.tools_registry as tools_registry
import core.channels as channels
import core.skills as skills
import core.memory as memory
# ---- 第二阶段模块（P1/M2/M4/P2/M7 指令层 + 约束层 + 编排 + 自进化）----
import core.workbench as workbench
import core.approval as approval
import core.memory_v2 as memory_v2
import core.canvas as canvas
import core.scheduler as scheduler
import core.subagent as subagent
import core.evolution as evolution
# ---- 招聘智能化系统（5 模块）----
import core.resume_scorer as resume_scorer
import core.interview as interview
import core.recruit_dashboard as recruit_dashboard
import core.salary_assist as salary_assist
import core.talent_map as talent_map
# ---- 深度构造（企业级能力 · 5 项）----
import core.provider_router as provider_router
import core.connectors as connectors
import core.soc_audit as soc_audit
import core.orchestration as orchestration
import core.multitenant as multitenant
# ---- Coding Agent（自生成工具工厂 · 源自《深入理解 AI Agent》第5章）----
import core.coding_agent as coding_agent
import core.eval_harness as eval_harness
import core.wb_workbench as wb_workbench
import core.experts as experts
import core.model_hub as model_hub
import core.rag_adapter as rag_adapter  # A 方案：外部 RAGFlow/FastGPT 适配层（可选后端）
import core.taskflow as taskflow  # 岗位任务流引擎：提示词解析 → 自动执行闭环
# ---- 劳动关系 / 薪酬 / 简历规则引擎（第四、五模块补充，移植自 hr-ai-workbench）----
import core.labor_relations as labor_relations
import core.salary_records as salary_records
import core.resume_screening as resume_screening
import core.backup as backup

# ---- 运行时建表（绕开冻结的 db.py），失败不阻塞主链路 ----
try:
    usage.init()
    tools_registry.init()
    skills.init()
    workbench.init()
    approval.init()
    memory_v2.init()
    scheduler.init()
    evolution.init()
    resume_scorer.init()
    interview.init()
    recruit_dashboard.init()
    salary_assist.init()
    talent_map.init()
    provider_router.init()
    connectors.init()
    soc_audit.init()
    orchestration.init()
    multitenant.init()
    coding_agent.init()
    eval_harness.init()
    wb_workbench.init()
    experts.init()
    model_hub.init()
    taskflow.init()  # 岗位任务流：加载 task_library.json + 初始化审计/编排
    labor_relations.init()
    salary_records.init()
except Exception:
    pass

# 上传白名单与大小上限（与边界一致：>10MB → 413；非白名单 → 415）
UPLOAD_ALLOWED = {".txt", ".md", ".markdown", ".docx", ".pdf"}
UPLOAD_MAX_BYTES = 10 * 1024 * 1024

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="MiniYuxi", version="0.1.0", description="轻量自研 HR 智能体平台（原生进程 · 零外部服务）")


# ---------------- 鉴权依赖 ----------------
def get_principal(authorization: str = Header(default="")) -> auth.Principal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "缺少 Bearer Token")
    body = auth.parse_token(authorization[7:])
    if not body:
        raise HTTPException(401, "Token 无效或已过期")
    return auth.Principal(body["tid"], body["sub"], body["role"])


def need(perm: str):
    def _dep(p: auth.Principal = Depends(get_principal)) -> auth.Principal:
        try:
            p.require(perm)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        return p

    return _dep


# ---------------- 模型 ----------------
class LoginIn(BaseModel):
    tenant: str = "default"
    username: str
    password: str


class DocIn(BaseModel):
    title: str
    text: str
    source: str = ""


class SearchIn(BaseModel):
    query: str
    top_k: int = 5


class ChatIn(BaseModel):
    question: str
    top_k: int = 5
    # 多轮上下文（可选）：[{"role":"user"|"assistant","content":"..."}]
    history: list = []


class TenantIn(BaseModel):
    id: str
    name: str


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class ResetIn(BaseModel):
    username: str
    new_password: str


class RagAskIn(BaseModel):
    question: str
    top_k: int = 5
    prefer: str = "auto"  # auto | ragflow | fastgpt | native


class AgentStartIn(BaseModel):
    flow: str = "recruit"


class AgentStepIn(BaseModel):
    run_id: str
    approve: bool = True
    note: str = ""


# ---------------- 基础 ----------------
@app.get("/api/health")
def health():
    search = {}
    try:
        search = tools_registry.search_backend_status()
    except Exception:
        search = {"default": "doubao"}
    return {
        "ok": True,
        "service": "MiniYuxi",
        "version": "0.1.0",
        "storage": {"db": "SQLite", "vector": f"sqlite-vec {db.vec_version()}", "fts": "FTS5"},
        "modes": {"llm": "online" if config.llm_enabled() else "offline-fallback",
                  "embedding": "online" if config.emb_enabled() else "bm25-only"},
        "search": search,
    }


@app.post("/api/auth/login")
def login(body: LoginIn):
    conn = db.connect()
    t = conn.execute("SELECT id FROM tenants WHERE id=?", (body.tenant,)).fetchone()
    if not t:
        raise HTTPException(404, "租户不存在")
    u = conn.execute("SELECT * FROM users WHERE tenant_id=? AND username=?", (body.tenant, body.username)).fetchone()
    if not u or not auth.verify_password(body.password, u["password_hash"], u["salt"]):
        # B 方案：登录失败也要留痕（原仅记录成功），用于异常登录监测
        db.audit(body.tenant, body.username, "login", "session", "fail")
        raise HTTPException(401, "用户名或密码错误")
    db.audit(body.tenant, body.username, "login", "session", "success")
    return {"token": auth.make_token({"tid": body.tenant, "sub": body.username, "role": u["role"]}),
            "role": u["role"], "tenant": body.tenant}


@app.get("/api/me")
def me(p: auth.Principal = Depends(get_principal)):
    return {"tenant": p.tenant_id, "user": p.username, "role": p.role, "perms": sorted(p.perms)}


# ---------------- 租户与用户（多租户 / 权限）----------------
@app.get("/api/tenants")
def list_tenants(p: auth.Principal = Depends(need("tenant.manage"))):
    return [dict(r) for r in db.connect().execute("SELECT * FROM tenants").fetchall()]


@app.post("/api/tenants")
def create_tenant(body: TenantIn, p: auth.Principal = Depends(need("tenant.manage"))):
    try:
        db.connect().execute("INSERT INTO tenants(id,name) VALUES(?,?)", (body.id, body.name))
        db.connect().commit()
    except Exception as exc:
        raise HTTPException(400, f"创建失败（可能已存在）：{exc}")
    db.audit(p.tenant_id, p.username, "tenant.create", body.id, body.name)
    return {"ok": True, "tenant": body.id}


@app.post("/api/users")
def create_user(body: UserIn, p: auth.Principal = Depends(need("user.manage"))):
    if body.role not in config.ROLE_PERMS:
        raise HTTPException(400, f"角色非法，可选：{list(config.ROLE_PERMS)}")
    h, s = auth.hash_password(body.password)
    try:
        db.connect().execute(
            "INSERT INTO users(id,tenant_id,username,password_hash,salt,role) VALUES(?,?,?,?,?,?)",
            (auth.new_id("u"), p.tenant_id, body.username, h, s, body.role),
        )
        db.connect().commit()
    except Exception as exc:
        raise HTTPException(400, f"创建失败（可能重名）：{exc}")
    db.audit(p.tenant_id, p.username, "user.create", body.username, body.role)
    return {"ok": True, "username": body.username, "role": body.role}


@app.get("/api/users")
def list_users(p: auth.Principal = Depends(need("user.manage"))):
    """B 方案：用户管理面板后端——列出本租户账号（不含口令明细）。"""
    rows = db.connect().execute(
        "SELECT id,tenant_id,username,role,created_at FROM users WHERE tenant_id=? ORDER BY username",
        (p.tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/me/password")
def change_password(body: PasswordIn, p: auth.Principal = Depends(get_principal)):
    """B 方案：自助改密——必须校验旧口令，防止越权改他人口令。"""
    if len(body.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    conn = db.connect()
    u = conn.execute(
        "SELECT * FROM users WHERE tenant_id=? AND username=?",
        (p.tenant_id, p.username),
    ).fetchone()
    if not u or not auth.verify_password(body.old_password, u["password_hash"], u["salt"]):
        db.audit(p.tenant_id, p.username, "password.change", p.username, "fail")
        raise HTTPException(401, "旧密码错误")
    h, s = auth.hash_password(body.new_password)
    conn.execute(
        "UPDATE users SET password_hash=?, salt=? WHERE tenant_id=? AND username=?",
        (h, s, p.tenant_id, p.username),
    )
    conn.commit()
    db.audit(p.tenant_id, p.username, "password.change", p.username, "success")
    return {"ok": True}


@app.post("/api/users/reset")
def reset_password(body: ResetIn, p: auth.Principal = Depends(need("user.manage"))):
    """B 方案：管理员重置某用户口令（不要求旧口令，仅限本租户）。"""
    if len(body.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    conn = db.connect()
    u = conn.execute(
        "SELECT * FROM users WHERE tenant_id=? AND username=?",
        (p.tenant_id, body.username),
    ).fetchone()
    if not u:
        raise HTTPException(404, "用户不存在")
    h, s = auth.hash_password(body.new_password)
    conn.execute(
        "UPDATE users SET password_hash=?, salt=? WHERE tenant_id=? AND username=?",
        (h, s, p.tenant_id, body.username),
    )
    conn.commit()
    db.audit(p.tenant_id, p.username, "user.reset", body.username, "admin")
    return {"ok": True, "username": body.username}


# ---------------- 知识库 ----------------
@app.get("/api/kb/docs")
def kb_list(p: auth.Principal = Depends(need("kb.read"))):
    return rag.list_documents(p.tenant_id)


@app.post("/api/kb/docs")
def kb_add(body: DocIn, p: auth.Principal = Depends(need("kb.write"))):
    res = rag.add_document(p.tenant_id, body.title, body.text, body.source)
    db.audit(p.tenant_id, p.username, "kb.add", res.get("doc_id", ""), body.title)
    return res


@app.delete("/api/kb/docs/{doc_id}")
def kb_del(doc_id: str, p: auth.Principal = Depends(need("kb.delete"))):
    n = rag.delete_document(p.tenant_id, doc_id)
    db.audit(p.tenant_id, p.username, "kb.delete", doc_id, f"chunks={n}")
    return {"ok": True, "removed_chunks": n}


@app.post("/api/kb/search")
def kb_search(body: SearchIn, p: auth.Principal = Depends(need("kb.read"))):
    return rag.search(p.tenant_id, body.query, body.top_k)


@app.post("/api/kb/upload")
async def kb_upload(file: UploadFile = File(...), p: auth.Principal = Depends(need("kb.write"))):
    """制度文档导入：支持 .docx/.pdf/.txt/.md，入库 chunks≥1 且可被检索命中。
    必须先过鉴权（kb.write），并强制带 tenant_id，否则视为越权漏洞。"""
    raw = await file.read()
    if len(raw) > UPLOAD_MAX_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"文件过大：{len(raw)} 字节，上限 {UPLOAD_MAX_BYTES} 字节（10MB）"},
        )
    suf = os.path.splitext(file.filename or "")[1].lower()
    if suf not in UPLOAD_ALLOWED:
        return JSONResponse(
            status_code=415,
            content={"detail": f"不支持的文件类型：{suf or '(无后缀)'}（允许：.txt/.md/.markdown/.docx/.pdf）"},
        )
    suffix = suf or ".tmp"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(raw)
        tmp.close()
        text = rag.parse_file(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    res = rag.add_document(p.tenant_id, file.filename or "未命名文档", text, file.filename or "")
    db.audit(p.tenant_id, p.username, "kb.upload", res.get("doc_id", ""), file.filename or "")
    return res


@app.post("/api/chat")
def chat(body: ChatIn, stream: bool = False, p: auth.Principal = Depends(need("chat"))):
    if not stream:
        return rag.answer(p.tenant_id, body.question, body.top_k, body.history or None)

    # ---- T5 SSE 流式：逐 token 推送给前端 ----
    def _event(payload: dict, name: str = "message") -> str:
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _gen():
        try:
            # 统一走自主 Agent Loop（rag.answer 内部已含 agent loop / 记忆 / 离线兜底 / skills）
            d = rag.answer(p.tenant_id, body.question, body.top_k, body.history or None)
            meta = {"citations": d.get("citations", []), "mode": d.get("mode")}
            if d.get("tool_calls_used"):
                meta["tool_calls_used"] = d["tool_calls_used"]
            if d.get("loop_trace"):
                meta["loop_trace"] = d["loop_trace"]
            if d.get("warnings"):
                meta["warnings"] = d["warnings"]
            yield _event(meta, "meta")
            ans = d.get("answer", "")
            for i in range(0, len(ans), 12):
                yield _event({"delta": ans[i:i + 12]})
                time.sleep(0.01)
        except Exception as exc:
            yield _event({"error": str(exc)[:200]})
        yield _event({}, "done")

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---------------- A 方案：HR 知识库问答入口（原生 RAG + 外部平台适配）----------------
@app.post("/api/rag/ask")
def rag_ask(body: RagAskIn, p: auth.Principal = Depends(need("kb.read"))):
    """向知识库提问。默认走原生 RAG；若配置了 RAGFlow/FastGPT 环境变量则优先外部平台，失败自动降级。"""
    try:
        return rag_adapter.ask(body.question, p.tenant_id, body.top_k, body.prefer)
    except Exception as exc:
        # 任何外部接入异常都不应让 HR 问答整体不可用
        return rag.answer(p.tenant_id, body.question, body.top_k, None)


# ---------------- T1 统一大模型网关 ----------------
@app.get("/api/gateway/models")
def gateway_models(p: auth.Principal = Depends(need("chat"))):
    return {"models": gateway.list_models(), "current": config.LLM_MODEL,
            "providers": config.LLM_PROVIDERS}


# ---------------- T2 MCP 工具层 ----------------
class ToolCallIn(BaseModel):
    name: str
    args: dict = {}


@app.get("/api/tools/list")
def tools_list(p: auth.Principal = Depends(need("chat"))):
    return {"tools": tools_registry.list_tools()}


@app.post("/api/tools/call")
def tools_call(body: ToolCallIn, p: auth.Principal = Depends(need("chat"))):
    return tools_registry.call_tool(body.name, body.args, tenant_id=p.tenant_id)


# ---------------- T3 Token 成本监控 ----------------
@app.get("/api/usage/stats")
def usage_stats(p: auth.Principal = Depends(need("chat"))):
    return usage.stats(p.tenant_id)


# ---------------- T4 企微 webhook ----------------
class WeComIn(BaseModel):
    content: str = ""
    text: dict = {}


@app.post("/api/channels/wecom/webhook")
def wecom_webhook(body: WeComIn):
    payload = {}
    if body.content:
        payload["content"] = body.content
    if isinstance(body.text, dict) and body.text.get("content"):
        payload["text"] = body.text
    return channels.handle_wecom(payload)


# ---------------- T6 闭环学习 ----------------
@app.get("/api/skills/list")
def skills_list(p: auth.Principal = Depends(need("chat"))):
    items = skills.list_skills(p.tenant_id)
    # 合并 skills/ 文件夹下的 Agent Skills（skills_catalog 实时扫描 SKILL.md）
    # 这类 skill 以 name 作为 id，UI 选中后 chat 端会按 name 加载其正文注入 system prompt
    try:
        from core import skills_catalog
        for s in skills_catalog.list_skills():
            items.append({
                "id": s["name"],
                "type": "folder",
                "name": s["name"],
                "title": s["name"],
                "description": s.get("description", ""),
                "trigger": s.get("trigger", ""),
                "sub": (s.get("description", "") or "")[:60],
            })
    except Exception:
        pass
    return {"skills": items}


@app.get("/api/experts/list")
def experts_list(p: auth.Principal = Depends(need("chat"))):
    return {"experts": experts.list_experts(p.tenant_id)}


# ---------------- 岗位任务流（提示词 → 自动执行闭环） ----------------
@app.get("/api/taskflow/roles")
def taskflow_roles(p: auth.Principal = Depends(need("chat"))):
    return {"roles": taskflow.list_roles()}


@app.get("/api/taskflow/list")
def taskflow_list(role: str = "", p: auth.Principal = Depends(need("chat"))):
    return {"tasks": taskflow.list_tasks(role or None)}


@app.get("/api/taskflow/workflow/{task_id}")
def taskflow_workflow(task_id: str, p: auth.Principal = Depends(need("chat"))):
    wf = taskflow.get_workflow(task_id)
    if not wf:
        raise HTTPException(404, "task not found")
    return wf


class TaskflowRunIn(BaseModel):
    task_id: str
    variables: dict = {}
    materials: list = []
    dry: bool = False
    auto_approve: bool = True
    model: str = ""          # 指定 LLM，如 deepseek:deepseek-chat；空=默认网关


@app.post("/api/taskflow/run")
def taskflow_run(body: TaskflowRunIn, p: auth.Principal = Depends(need("chat"))):
    return taskflow.run_task(body.task_id, body.variables, body.materials,
                             tenant_id=p.tenant_id, dry=body.dry,
                             auto_approve=body.auto_approve,
                             model=body.model or None)


# ---------------- Agent 编排 ----------------
@app.get("/api/agent/flows")
def flows(p: auth.Principal = Depends(need("agent.run"))):
    return agent.list_flows()


@app.post("/api/agent/start")
def agent_start(body: AgentStartIn, p: auth.Principal = Depends(need("agent.run"))):
    return agent.start(p.tenant_id, body.flow)


@app.post("/api/agent/step")
def agent_step(body: AgentStepIn, p: auth.Principal = Depends(need("agent.run"))):
    return agent.step(body.run_id, body.approve, body.note)


@app.post("/api/agent/run")
def agent_run_all(body: AgentStepIn, p: auth.Principal = Depends(need("agent.run"))):
    return agent.run_all(body.run_id, auto_approve=body.approve)


@app.get("/api/agent/run/{run_id}")
def agent_get(run_id: str, p: auth.Principal = Depends(need("agent.run"))):
    r = agent.get_run(run_id)
    if not r:
        raise HTTPException(404, "run 不存在")
    return r


# ---------------- 审计 ----------------
@app.get("/api/audit")
def audit_list(limit: int = 50, p: auth.Principal = Depends(need("audit.read"))):
    rows = db.connect().execute(
        "SELECT * FROM audit_logs WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (p.tenant_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------- P1 工作台（可观测性聚合）----------------
@app.get("/api/workbench")
def workbench_get(p: auth.Principal = Depends(need("chat"))):
    try:
        workbench.rollup_daily()
    except Exception:
        pass
    return workbench.aggregate(p.tenant_id)


# ---------------- M2 审批卡（HITL 约束层）----------------
class ApprovalCreateIn(BaseModel):
    tool_name: str
    args: dict = {}
    risk: str = "high"
    resume_token: str = ""
    requested_by: str = ""


class ApprovalDecideIn(BaseModel):
    approve: bool = True
    by: str = ""
    note: str = ""


@app.post("/api/approvals")
def approvals_create(body: ApprovalCreateIn, p: auth.Principal = Depends(need("agent.run"))):
    aid = approval.create(p.tenant_id, body.tool_name, json.dumps(body.args, ensure_ascii=False),
                          body.requested_by or p.username, body.risk, body.resume_token)
    db.audit(p.tenant_id, p.username, "approval.create", aid, body.tool_name)
    return {"id": aid, "status": "pending", "tool_name": body.tool_name}


@app.get("/api/approvals")
def approvals_list(status: str = "pending", p: auth.Principal = Depends(need("agent.run"))):
    if status == "all":
        return _all_approvals(p.tenant_id)
    return approval.list_pending(p.tenant_id)


def _all_approvals(tenant_id):
    try:
        rows = db.connect().execute(
            "SELECT * FROM approvals WHERE tenant_id=? ORDER BY id DESC LIMIT 100", (tenant_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


@app.post("/api/approvals/{aid}/decide")
def approvals_decide(aid: str, body: ApprovalDecideIn, p: auth.Principal = Depends(need("agent.run"))):
    d = approval.decide(aid, body.approve, by=body.by or p.username, note=body.note)
    db.audit(p.tenant_id, p.username, "approval.decide", aid, "approved" if body.approve else "rejected")
    return d


# ---------------- M4 记忆深化（三层记忆）----------------
class ExperienceIn(BaseModel):
    text: str
    source: str = ""


@app.post("/api/memory_v2/experience")
def memory_exp(body: ExperienceIn, p: auth.Principal = Depends(need("chat"))):
    memory_v2.append_experience(p.tenant_id, body.text, body.source)
    return {"ok": True}


@app.get("/api/memory_v2/distill")
def memory_distill(top_n: int = 3, p: auth.Principal = Depends(need("chat"))):
    return {"notes": memory_v2.distill(p.tenant_id, top_n)}


# ---------------- P2 画布 + 定时 Loop ----------------
class CanvasIn(BaseModel):
    workflow: dict


def _canvas_handlers(tenant_id):
    def h_start(node, g):
        return {"ok": True}

    def h_end(node, g):
        return {"ok": True}

    def h_knowledge(node, g):
        q = node.get("query") or g.get("query") or ""
        try:
            res = rag.search(tenant_id, q, 3)
            return {"hits": len(res), "first": (res[0].get("text", "") if res else "")[:80]}
        except Exception as e:  # noqa
            return {"error": str(e)[:120]}

    def h_tool(node, g):
        try:
            return tools_registry.call_tool(node.get("tool", ""), node.get("args", {}), tenant_id=tenant_id)
        except Exception as e:  # noqa
            return {"error": str(e)[:120]}

    def h_llm(node, g):
        prompt = node.get("prompt") or ""
        try:
            d = rag.answer(tenant_id, prompt, 3, None)
            return {"answer": (d.get("answer", "") or "")[:200]}
        except Exception as e:  # noqa
            return {"error": str(e)[:120], "echo": prompt[:120]}

    def h_approval(node, g):
        aid = approval.create(tenant_id, node.get("tool", "agent.run"),
                              json.dumps(node.get("args", {}), ensure_ascii=False),
                              "canvas", resume_token=node.get("id", ""))
        return {"approval_id": aid, "status": "pending", "note": "需人工审批后继续"}

    def h_subagent(node, g):
        task = node.get("task") or ""
        return subagent.delegate(task,
                                 generator_fn=lambda t, c: "草稿：针对「%s」的初步方案。" % t,
                                 judge_fn=lambda d, c: subagent.rule_judge(d, {"min_len": 5, "must_contain": ["方案"]}))

    def h_condition(node, g):
        return {"pass": True}

    return {"start": h_start, "end": h_end, "knowledge": h_knowledge, "tool": h_tool,
            "llm": h_llm, "approval": h_approval, "subagent": h_subagent, "condition": h_condition}


@app.post("/api/canvas/validate")
def canvas_validate(body: CanvasIn, p: auth.Principal = Depends(need("agent.run"))):
    ok, errs = canvas.validate(body.workflow)
    return {"ok": ok, "errors": errs}


@app.post("/api/canvas/run")
def canvas_run(body: CanvasIn, p: auth.Principal = Depends(need("agent.run"))):
    ok, errs = canvas.validate(body.workflow)
    if not ok:
        return JSONResponse(status_code=400, content={"detail": "工作流校验失败", "errors": errs})
    trace = canvas.execute(body.workflow, {}, _canvas_handlers(p.tenant_id))
    db.audit(p.tenant_id, p.username, "canvas.run", "run", str(len(trace.get("trace", []))) + " nodes")
    return trace


class ScheduleIn(BaseModel):
    name: str
    spec: dict
    payload: dict = {}


@app.get("/api/schedules")
def schedules_list(p: auth.Principal = Depends(need("agent.run"))):
    try:
        rows = db.connect().execute(
            "SELECT id,name,spec,payload,tenant_id,last_run,status FROM schedules "
            "WHERE tenant_id=? ORDER BY id DESC", (p.tenant_id,)
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "spec": json.loads(r["spec"]),
                 "payload": json.loads(r["payload"]), "last_run": r["last_run"], "status": r["status"]}
                for r in rows]
    except Exception:
        return []


@app.post("/api/schedules")
def schedules_create(body: ScheduleIn, p: auth.Principal = Depends(need("agent.run"))):
    jid = scheduler.register(body.name, body.spec, body.payload, tenant_id=p.tenant_id)
    db.audit(p.tenant_id, p.username, "schedule.create", jid, body.name)
    return {"id": jid, "status": "active"}


@app.post("/api/schedules/{jid}/run")
def schedules_run(jid: str, p: auth.Principal = Depends(need("agent.run"))):
    scheduler.mark_run(jid)
    return {"ok": True}


# ---------------- 子 Agent（生成器/评判器分离）----------------
class SubAgentIn(BaseModel):
    task: str
    max_rounds: int = 3
    criteria: dict = {"min_len": 5, "must_contain": ["方案"]}


@app.post("/api/subagent/run")
def subagent_run(body: SubAgentIn, p: auth.Principal = Depends(need("agent.run"))):
    res = subagent.delegate(
        body.task,
        generator_fn=lambda t, c: "草稿：针对「%s」的初步方案，包含风险与建议。" % t,
        judge_fn=lambda d, c: subagent.rule_judge(d, body.criteria),
        max_rounds=body.max_rounds,
    )
    return res


# ---------------- M7 自进化引擎 + Curator ----------------
class EvoProposeIn(BaseModel):
    topic: str
    sources: list = []


class EvoPruneIn(BaseModel):
    skill_id: str
    reason: str = ""
    by: str = ""


@app.post("/api/evolution/propose")
def evo_propose(body: EvoProposeIn, p: auth.Principal = Depends(need("agent.run"))):
    return evolution.propose_skill(p.tenant_id, body.topic, body.sources)


@app.post("/api/evolution/review")
def evo_review(body: dict, p: auth.Principal = Depends(need("agent.run"))):
    return evolution.curator_review(body)


@app.post("/api/evolution/skills")
def evo_save(body: dict, p: auth.Principal = Depends(need("agent.run"))):
    sid = evolution.save_skill(p.tenant_id, body)
    db.audit(p.tenant_id, p.username, "evolution.save", sid, body.get("name", ""))
    return {"id": sid}


@app.get("/api/evolution/skills")
def evo_list(p: auth.Principal = Depends(need("agent.run"))):
    return {"skills": evolution.list_skills(p.tenant_id)}


@app.post("/api/evolution/prune")
def evo_prune(body: EvoPruneIn, p: auth.Principal = Depends(need("agent.run"))):
    bk = evolution.prune(body.skill_id, reason=body.reason, by=body.by or p.username)
    db.audit(p.tenant_id, p.username, "evolution.prune", body.skill_id, body.reason)
    return {"backup_id": bk}


# ---------------- 招聘智能化系统（5 模块）----------------
class ResumeScoreIn(BaseModel):
    job_title: str
    resume_text: str
    name: str = ""


class ResumeRankIn(BaseModel):
    job_title: str
    candidates: list = []


@app.post("/api/recruit/resume/score")
def recruit_resume_score(body: ResumeScoreIn, p: auth.Principal = Depends(need("chat"))):
    return resume_scorer.score(body.resume_text, body.job_title, p.tenant_id)


@app.post("/api/recruit/resume/rank")
def recruit_resume_rank(body: ResumeRankIn, p: auth.Principal = Depends(need("chat"))):
    return {"ranked": resume_scorer.rank_candidates(body.candidates, body.job_title, p.tenant_id)}


@app.get("/api/recruit/competency")
def recruit_competency(job_title: str, p: auth.Principal = Depends(need("chat"))):
    return {"job_title": job_title, "weights": resume_scorer.get_competency(p.tenant_id, job_title)}


class CompetencyIn(BaseModel):
    job_title: str
    weights: dict


@app.post("/api/recruit/competency")
def recruit_competency_set(body: CompetencyIn, p: auth.Principal = Depends(need("chat"))):
    resume_scorer.save_competency(p.tenant_id, body.job_title, body.weights)
    return {"ok": True}


class InterviewGenIn(BaseModel):
    job_title: str
    resume_text: str


@app.post("/api/recruit/interview/questions")
def recruit_interview_q(body: InterviewGenIn, p: auth.Principal = Depends(need("chat"))):
    return {"questions": interview.generate_questions(body.resume_text, body.job_title, p.tenant_id)}


class InterviewQIn(BaseModel):
    job_category: str
    dimension: str
    question: str


@app.post("/api/recruit/interview/bank")
def recruit_interview_bank_add(body: InterviewQIn, p: auth.Principal = Depends(need("chat"))):
    interview.add_question(p.tenant_id, body.job_category, body.dimension, body.question)
    return {"ok": True}


@app.get("/api/recruit/interview/bank")
def recruit_interview_bank(job_category: str = "", p: auth.Principal = Depends(need("chat"))):
    return {"questions": interview.list_questions(job_category or None, p.tenant_id)}


class InterviewEvalIn(BaseModel):
    candidate: str
    job_title: str
    scores: dict = {}
    summary: str = ""


@app.post("/api/recruit/interview/evaluate")
def recruit_interview_eval(body: InterviewEvalIn, p: auth.Principal = Depends(need("chat"))):
    interview.save_evaluation(p.tenant_id, body.candidate, body.job_title, body.scores, body.summary)
    return {"ok": True}


@app.get("/api/recruit/interview/evaluations")
def recruit_interview_evals(p: auth.Principal = Depends(need("chat"))):
    return {"evaluations": interview.list_evaluations(p.tenant_id)}


class FunnelIn(BaseModel):
    week: str
    stage: str
    cnt: int


@app.post("/api/recruit/funnel")
def recruit_funnel_record(body: FunnelIn, p: auth.Principal = Depends(need("agent.run"))):
    recruit_dashboard.record(p.tenant_id, body.week, body.stage, body.cnt)
    return {"ok": True}


@app.get("/api/recruit/dashboard")
def recruit_dashboard_view(week: str = "", p: auth.Principal = Depends(need("agent.run"))):
    if week:
        return {"week": week, "funnel": recruit_dashboard.weekly(p.tenant_id, week)}
    return recruit_dashboard.summary(p.tenant_id)


class MarketIn(BaseModel):
    job_title: str
    p25: float
    p50: float
    p75: float


@app.post("/api/recruit/salary/market")
def recruit_salary_market(body: MarketIn, p: auth.Principal = Depends(need("agent.run"))):
    salary_assist.set_market(p.tenant_id, body.job_title, body.p25, body.p50, body.p75)
    return {"ok": True}


class SalaryAdviseIn(BaseModel):
    job_title: str
    budget: float
    candidate_level: str = "mid"


@app.post("/api/recruit/salary/advise")
def recruit_salary_advise(body: SalaryAdviseIn, p: auth.Principal = Depends(need("agent.run"))):
    return salary_assist.advise(body.job_title, body.budget, body.candidate_level, p.tenant_id)


class TalentIn(BaseModel):
    name: str
    company: str
    title: str
    domain: str
    tags: str = ""
    status: str = "储备"
    source: str = ""


@app.post("/api/recruit/talent")
def recruit_talent_add(body: TalentIn, p: auth.Principal = Depends(need("agent.run"))):
    talent_map.add_talent(p.tenant_id, body.name, body.company, body.title, body.domain, body.tags, body.status, body.source)
    return {"ok": True}


@app.get("/api/recruit/talent/domain")
def recruit_talent_domain(domain: str, p: auth.Principal = Depends(need("agent.run"))):
    return {"talents": talent_map.list_by_domain(domain, p.tenant_id)}


@app.get("/api/recruit/talent/company")
def recruit_talent_company(company: str, p: auth.Principal = Depends(need("agent.run"))):
    return {"talents": talent_map.list_by_company(company, p.tenant_id)}


@app.get("/api/recruit/talent/stats")
def recruit_talent_stats(p: auth.Principal = Depends(need("agent.run"))):
    return talent_map.stats(p.tenant_id)


# =====================================================================
#  深度构造 · 企业级能力（项1-5）
# =====================================================================

# ---- 项1：运行时热切换与多供应商路由 ----
@app.get("/api/gateway/providers")
def gw_providers(p: auth.Principal = Depends(need("chat"))):
    return {"providers": provider_router.list_providers(), "active": provider_router.get_active()}


class ProviderIn(BaseModel):
    id: str
    name: str
    kind: str = "openai"
    base_url: str
    api_key: str = ""
    model: str
    priority: int = 0
    enabled: bool = True


@app.post("/api/gateway/providers")
def gw_provider_add(body: ProviderIn, p: auth.Principal = Depends(need("agent.run"))):
    pid = provider_router.register_provider(body.dict(), db.connect())
    return {"ok": True, "id": pid}


class ActiveIn(BaseModel):
    provider_id: str


@app.post("/api/gateway/active")
def gw_set_active(body: ActiveIn, p: auth.Principal = Depends(need("agent.run"))):
    provider_router.set_active(body.provider_id, db.connect())
    return {"ok": True, "active": body.provider_id}


# ---- 项2：MCP 原生适配层（微信/企微/CRM/ERP/飞书）----
@app.get("/api/connectors")
def conn_list(p: auth.Principal = Depends(need("agent.run"))):
    return {"connectors": connectors.list_connectors()}


class ConnectorIn(BaseModel):
    name: str
    kind: str
    config: dict = {}


@app.post("/api/connectors")
def conn_add(body: ConnectorIn, p: auth.Principal = Depends(need("agent.run"))):
    cid = connectors.register(body.name, body.kind, body.config, db.connect())
    return {"ok": True, "id": cid}


@app.post("/api/connectors/health")
def conn_health(p: auth.Principal = Depends(need("agent.run"))):
    return {"health": connectors.health(db.connect())}


class ConnSendIn(BaseModel):
    target: str
    text: str


@app.post("/api/connectors/{cid}/send")
def conn_send(cid: str, body: ConnSendIn, p: auth.Principal = Depends(need("agent.run"))):
    return connectors.send_message(cid, body.target, body.text, db.connect())


# ---- 项3：SOC 级结构化审计（哈希防篡改链）----
@app.post("/api/audit/events")
def audit_log(body: dict, p: auth.Principal = Depends(need("agent.run"))):
    ev = dict(body); ev["tenant_id"] = ev.get("tenant_id") or p.tenant_id
    ev["actor"] = ev.get("actor") or p.username
    ev["role"] = ev.get("role") or p.role
    return soc_audit.log(ev, db.connect())


@app.get("/api/audit/events")
def audit_query(tenant_id: str = "", action: str = "", result: str = "",
                severity: str = "", p: auth.Principal = Depends(need("audit.read"))):
    filt = {k: v for k, v in {"tenant_id": tenant_id, "action": action,
            "result": result, "severity": severity}.items() if v}
    return {"events": soc_audit.query(filt, conn=db.connect())}


@app.get("/api/audit/verify")
def audit_verify(p: auth.Principal = Depends(need("audit.read"))):
    return soc_audit.verify_chain(db.connect())


@app.get("/api/audit/report")
def audit_report(p: auth.Principal = Depends(need("audit.read"))):
    return soc_audit.export(db.connect())


@app.get("/api/audit/stats")
def audit_stats(p: auth.Principal = Depends(need("audit.read"))):
    return soc_audit.stats(db.connect())


# ---- 项4：复杂多 Agent 协同 + 工作流自动化 ----
def _team_llm(tenant_id):
    def fn(system, prompt):
        r = gateway.chat(system, prompt, tenant_id=tenant_id)
        return (r.get("text") or "", None)
    return fn


class TeamIn(BaseModel):
    task: str
    roles: list
    max_rounds: int = 2


@app.post("/api/orchestration/team")
def orch_team(body: TeamIn, p: auth.Principal = Depends(need("agent.run"))):
    return orchestration.run_team(body.task, body.roles, db.connect(),
                                   llm_fn=_team_llm(p.tenant_id), max_rounds=body.max_rounds)


class AutomationIn(BaseModel):
    workflow: dict
    trigger: str = "manual"


@app.post("/api/orchestration/automation")
def orch_automation(body: AutomationIn, p: auth.Principal = Depends(need("agent.run"))):
    return orchestration.run_automation(body.workflow, body.trigger, {},
                                         _canvas_handlers(p.tenant_id), db.connect())


# ---- 项5：多租户隔离 + 合规就绪度 ----
@app.get("/api/tenant/policy")
def tenant_policy(p: auth.Principal = Depends(need("agent.run"))):
    return {"policy": multitenant.get_policy(p.tenant_id)}


class TenantPolicyIn(BaseModel):
    mlps_level: str = "unset"
    data_residency: str = "cn-guangdong"
    quota_daily_calls: int = 1000
    quota_kb_mb: int = 100
    cmk_enabled: bool = False
    cmk_key_id: str = ""


@app.post("/api/tenant/policy")
def tenant_policy_set(body: TenantPolicyIn, p: auth.Principal = Depends(need("tenant.manage"))):
    multitenant.set_policy(p.tenant_id, body.dict(), db.connect())
    return {"ok": True}


class EnforceIn(BaseModel):
    action: str
    usage_counts: dict = {}


@app.post("/api/tenant/enforce")
def tenant_enforce(body: EnforceIn, p: auth.Principal = Depends(need("agent.run"))):
    return multitenant.enforce(p.tenant_id, body.action, body.usage_counts, db.connect())


@app.get("/api/tenant/readiness")
def tenant_readiness(p: auth.Principal = Depends(need("tenant.manage"))):
    return multitenant.readiness(db.connect())


# ---------------- Coding Agent（自生成工具工厂 · 源自《深入理解 AI Agent》第5章）----------------
class CodingGenIn(BaseModel):
    description: str
    code: str = ""
    name: str = ""


@app.post("/api/coding/generate")
def coding_generate(body: CodingGenIn, p: auth.Principal = Depends(need("agent.run"))):
    d = coding_agent.generate_tool(p.tenant_id, body.description, code=body.code or None, name=body.name or None)
    if d.get("ok"):
        db.audit(p.tenant_id, p.username, "coding.generate", d.get("name", ""), body.description[:80])
    return d


@app.get("/api/coding/list")
def coding_list(p: auth.Principal = Depends(need("agent.run"))):
    return {"tools": coding_agent.list_generated(p.tenant_id)}


@app.delete("/api/coding/{name}")
def coding_remove(name: str, p: auth.Principal = Depends(need("agent.run"))):
    d = coding_agent.remove_tool(p.tenant_id, name)
    db.audit(p.tenant_id, p.username, "coding.remove", name, "")
    return d


@app.get("/api/coding/blueprint")
def coding_blueprint(p: auth.Principal = Depends(need("chat"))):
    return coding_agent.get_blueprint()


# ---------------- 评估端点 ----------------
@app.get("/api/eval/run")
def eval_run(k: int = 1, run_name: str = "demo", p: auth.Principal = Depends(need("agent.run"))):
    """运行评估（默认 demo 任务集）。"""
    h = eval_harness.EvalHarness(p.tenant_id)
    for t in eval_harness.build_demo_tasks():
        h.add_task(t)
    report = h.run_all(k=k)
    eval_harness.save_report(run_name, report)
    db.audit(p.tenant_id, p.username, "eval.run", run_name, f"tasks={report['total_tasks']} pass@1={report['pass_at_1']:.2f}")
    return report


# ---------------- WorkBuddy (www.workbuddy.cn/app) 复刻工作台 ----------------
_WB_ICONS_CACHE: str | None = None


def _wb_icons_json() -> str:
    """原站快捷入口图标 SVG（auto-js-reverse 逆向抓取所得），注入复刻页。"""
    global _WB_ICONS_CACHE
    if _WB_ICONS_CACHE is None:
        try:
            data = json.loads((WEB_DIR / "wb_icons.json").read_text(encoding="utf-8"))
            _WB_ICONS_CACHE = json.dumps(data, ensure_ascii=False)
        except Exception:
            _WB_ICONS_CACHE = "{}"
    return _WB_ICONS_CACHE


@app.get("/wb")
def wb_page():
    html = (WEB_DIR / "wb_workbench.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__ICONS_JSON__", _wb_icons_json()))


@app.get("/wb/wb_workbench.css")
def wb_css():
    return FileResponse(WEB_DIR / "wb_workbench.css", media_type="text/css")


@app.get("/wb/wb_workbench.js")
def wb_js():
    return FileResponse(WEB_DIR / "wb_workbench.js", media_type="application/javascript")


@app.get("/api/wb/bootstrap")
def wb_bootstrap(p: auth.Principal = Depends(need("chat"))):
    return wb_workbench.bootstrap(p.tenant_id)


@app.post("/api/wb/chat")
def wb_chat(body: dict, p: auth.Principal = Depends(need("chat"))):
    return wb_workbench.chat(
        p.tenant_id, body.get("message", ""), body.get("scene", ""), body.get("history"),
        provider=body.get("provider"), model=body.get("model"),
        mode=body.get("mode", "agent"),
        allow_full_access=bool(body.get("allow_full_access", True)),
        expert=body.get("expert"), skill=body.get("skill"),
        connector_ids=body.get("connector_ids") or [],
        attached_doc_ids=body.get("attached_doc_ids") or []
    )


@app.get("/api/wb/stats")
def wb_stats(p: auth.Principal = Depends(need("chat"))):
    return wb_workbench.stats(p.tenant_id)


# =====================================================================
#  多模型中枢（Model Hub）：目录 / 路由 / 单模型 / 并行对比 / 任务记录
# =====================================================================
@app.get("/api/models/catalog")
def models_catalog(p: auth.Principal = Depends(need("chat"))):
    return model_hub.catalog()


class RouteIn(BaseModel):
    message: str = ""
    strategy: str = "balanced"


@app.post("/api/models/route")
def models_route(body: RouteIn, p: auth.Principal = Depends(need("chat"))):
    return model_hub.route(body.message, body.strategy if body.strategy in
                           ("economy", "balanced", "premium") else "balanced")


class MChatIn(BaseModel):
    message: str
    model_id: str = ""          # 空 = 自动路由
    strategy: str = "balanced"
    system: str = ""
    history: list = []
    temperature: float | None = None


@app.post("/api/models/chat")
def models_chat(body: MChatIn, p: auth.Principal = Depends(need("chat"))):
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日")
    except Exception:
        today = datetime.now().strftime("%Y年%m月%d日")
    SYS = body.system or f"你是 MiniYuxi 多模型助手，回答简洁、结构化、不编造。今天是{today}，涉及实时日期的问题请按此回答。"

    if body.model_id:
        m = model_hub._MODEL.get(body.model_id, {})
        rid = {
            "task_type": "general", "name": "通用问答", "matched": False, "confidence": 0.5,
            "strategy": body.strategy,
            "model_id": body.model_id,
            "model_name": m.get("name", body.model_id),
            "provider": m.get("provider", ""),
            "reason": f"用户指定模型：{m.get('name', body.model_id)}",
            "candidates": [],
        }
        mid = body.model_id
    else:
        rid = model_hub.route(body.message, body.strategy)
        mid = rid["model_id"]

    r = model_hub.chat(mid, SYS, body.message, body.history, p.tenant_id, body.temperature)
    # 自动路由首选模型不可用时，回退到默认模型，保证回答不中断；指定模型失败不回退，避免违逆用户选择
    if (not r.get("ok")) and (not body.model_id):
        fb = model_hub.default_model_id()
        if fb and fb != mid:
            r = model_hub.chat(fb, SYS, body.message, body.history, p.tenant_id, body.temperature)
            rid = {**rid, "model_id": fb,
                   "model_name": model_hub._MODEL.get(fb, {}).get("name", fb),
                   "reason": (rid.get("reason", "") or "") + "（首选不可用，已回退默认模型）"}
    model_hub.record_task(p.tenant_id, "chat", body.message, rid["task_type"], body.strategy,
                          [mid], r.get("model_name", mid), bool(r.get("ok")),
                          r.get("latency_ms", 0), r.get("cost", 0), r.get("tokens", 0),
                          r.get("text", ""))
    return {**r, "routed": rid, "auto": not body.model_id}


class CompareIn(BaseModel):
    message: str
    model_ids: list = []
    merge: bool = False
    judge_model_id: str = ""
    system: str = ""
    history: list = []


@app.post("/api/models/compare")
def models_compare(body: CompareIn, p: auth.Principal = Depends(need("chat"))):
    ids = [i for i in body.model_ids if i]
    if not ids:
        ids = [c["id"] for c in model_hub.route(body.message)["candidates"][:3]]
    if not ids:
        return {"ok": False, "error": "no_model_available", "results": [], "merged": None}
    results = model_hub.compare(ids, body.system or "你是 MiniYuxi 多模型助手，回答简洁、结构化、不编造。",
                                body.message, body.history, p.tenant_id)
    merged = None
    if body.merge:
        merged = model_hub.merge(body.message, results, body.judge_model_id or None, p.tenant_id)
    ok_any = any(r.get("ok") for r in results)
    lat = max((r.get("latency_ms") or 0) for r in results) if results else 0
    cost = sum((r.get("cost") or 0) for r in results) + ((merged or {}).get("cost") or 0)
    tok = sum((r.get("tokens") or 0) for r in results)
    tid = model_hub.record_task(p.tenant_id, "compare", body.message,
                                model_hub.classify(body.message)["task_type"], "compare",
                                ids, f"{len(results)} 模型并行", ok_any, lat, cost, tok,
                                (merged or {}).get("text") or "")
    return {"ok": ok_any, "task_id": tid, "results": results, "merged": merged,
            "total_cost": round(cost, 6), "total_latency_ms": lat}


@app.get("/api/models/tasks")
def models_tasks(limit: int = 30, p: auth.Principal = Depends(need("chat"))):
    return {"tasks": model_hub.list_tasks(p.tenant_id, limit),
            "stats": model_hub.task_stats(p.tenant_id)}


class ProvIn(BaseModel):
    provider_id: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


@app.post("/api/models/providers")
def models_provider_set(body: ProvIn, p: auth.Principal = Depends(need("agent.run"))):
    model_hub.set_provider(body.provider_id, body.api_key, body.base_url, body.enabled)
    return {"ok": True, "provider": body.provider_id}


class TestIn(BaseModel):
    model_id: str


@app.post("/api/models/test")
def models_test(body: TestIn, p: auth.Principal = Depends(need("chat"))):
    r = model_hub.chat(body.model_id, "你是连通性探针。", "只回复两个字：正常",
                       tenant_id=p.tenant_id)
    return {"ok": r.get("ok"), "model_id": body.model_id, "model_name": r.get("model_name"),
            "latency_ms": r.get("latency_ms", 0), "err": r.get("err", ""),
            "text": (r.get("text") or "")[:40]}


# ---------------- 劳动关系 / 薪酬 / 简历规则引擎 ----------------
class ContractIn(BaseModel):
    id: int | None = None
    name: str = ""
    personnel: str = ""
    start_date: str = ""
    end_date: str = ""
    is_indefinite: int = 0
    contract_no: int = 1
    contract_type: str = "固定期限"
    status: str = "履行中"
    probation_start: str = ""
    probation_end: str = ""
    note: str = ""


@app.get("/api/labor/dashboard")
def labor_dashboard(p: auth.Principal = Depends(need("chat"))):
    return labor_relations.dashboard(p.tenant_id)


@app.get("/api/labor/contracts")
def labor_contracts(status: str = "", p: auth.Principal = Depends(need("chat"))):
    return {"contracts": labor_relations.list_contracts(p.tenant_id, status or None)}


@app.post("/api/labor/contracts")
def labor_contract_upsert(body: ContractIn, p: auth.Principal = Depends(need("kb.write"))):
    cid = labor_relations.upsert_contract(tenant_id=p.tenant_id, **body.model_dump())
    db.audit(p.tenant_id, p.username, "labor.contract.upsert", str(cid), body.name)
    return {"ok": True, "id": cid}


@app.delete("/api/labor/contracts/{cid}")
def labor_contract_delete(cid: int, p: auth.Principal = Depends(need("kb.write"))):
    labor_relations.delete_contract(cid)
    db.audit(p.tenant_id, p.username, "labor.contract.delete", str(cid))
    return {"ok": True}


@app.get("/api/labor/todos")
def labor_todos(status: str = "open", p: auth.Principal = Depends(need("chat"))):
    return {"todos": labor_relations.list_todos(p.tenant_id, status)}


@app.post("/api/labor/todos/{tid}/resolve")
def labor_todo_resolve(tid: int, p: auth.Principal = Depends(need("kb.write"))):
    labor_relations.resolve_todo(tid)
    return {"ok": True}


@app.post("/api/labor/sync")
def labor_sync(p: auth.Principal = Depends(need("kb.write"))):
    """手动触发合同预警重扫（每日也会由调度自动跑）。"""
    r = labor_relations.sync_all(p.tenant_id)
    db.audit(p.tenant_id, p.username, "labor.sync", "", f"生成 {r['generated']} 条待办")
    return {"ok": True, **r}


class SalaryIn(BaseModel):
    id: int | None = None
    emp_name: str = ""
    month: str = ""
    base_salary: int = 0
    performance: int = 0
    subsidy: int = 0
    overtime_pay: int = 0
    social_insurance: int = 0
    housing_fund: int = 0
    tax: int = 0
    other_deduct: int = 0
    note: str = ""


@app.get("/api/salary/records")
def salary_records_list(month: str = "", emp_name: str = "", p: auth.Principal = Depends(need("chat"))):
    return {"records": salary_records.list_records(p.tenant_id, month or None, emp_name or None)}


@app.get("/api/salary/summary")
def salary_summary(month: str = "", p: auth.Principal = Depends(need("chat"))):
    return {"summary": salary_records.month_summary(p.tenant_id, month or None)}


@app.post("/api/salary/records")
def salary_record_add(body: SalaryIn, p: auth.Principal = Depends(need("kb.write"))):
    rid = salary_records.add_record(tenant_id=p.tenant_id, **body.model_dump())
    db.audit(p.tenant_id, p.username, "salary.record.add", str(rid), body.emp_name)
    return {"ok": True, "id": rid}


class SalaryQAIn(BaseModel):
    question: str = ""


@app.post("/api/salary/qa")
def salary_qa(body: SalaryQAIn, p: auth.Principal = Depends(need("chat"))):
    return salary_records.salary_qa(body.question, p.tenant_id)


class ResumeScreenIn(BaseModel):
    text: str = ""
    role: str = ""
    hard_cond: dict = {}
    weights: dict = {}


@app.post("/api/resume/screen")
def resume_screen(body: ResumeScreenIn, p: auth.Principal = Depends(need("chat"))):
    """规则引擎初筛（DeepSeek 离线降级 / 双轨交叉校验用）。"""
    return resume_screening.screen_resume(body.text, body.role, body.hard_cond or None,
                                          body.weights or None)


# ---------------- 前端 ----------------
@app.get("/")
def index():
    """主界面 = MiniYuxi 智能工作台（外观同 /wb 复刻，字样已改 MiniYuxi）。
    注入快捷入口图标 JSON（__ICONS_JSON__ 占位符）。"""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__ICONS_JSON__", _wb_icons_json()))


@app.get("/legacy")
def legacy():
    """保留的旧版多模块主界面（功能不丢，按需访问）。"""
    return FileResponse(WEB_DIR / "index_legacy.html")


@app.exception_handler(PermissionError)
def _perm(req, exc):  # pragma: no cover
    return JSONResponse(status_code=403, content={"detail": str(exc)})
