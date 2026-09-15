"""WorkBuddy (www.workbuddy.cn/app) 复刻工作台 —— 后端支撑模块。

来源：用 auto-js-reverse 对 https://www.workbuddy.cn/app 做逆向（CDP 抓取 DOM/computed style、
CSS 变量、静态资源与交互结构）后，按 MiniYuxi 技术栈复刻。

职责：
  1. 维护复刻页的静态配置（导航、场景分组、概览指标）；
  2. 为复刻页提供 /api/wb/chat 的后端能力：RAG 检索引用 + LLM 生成；
  3. 后端不可用时明确返回 degraded，由前端降级为本地占位回复（见 web/wb_workbench.js）。

不改动 core/db.py（三指纹红线），运行时 CREATE TABLE IF NOT EXISTS。
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import db

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS wb_replica_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    event TEXT NOT NULL,
    scene TEXT DEFAULT '',
    payload TEXT DEFAULT '',
    ts REAL NOT NULL
)
"""

# ---------------- 静态配置（顶部栏 = 旧 /legacy 功能入口） ----------------
NAV_ITEMS = ["新建", "导入", "知识库", "流程", "模型切换", "成本管理", "工作台"]

# 「日常办公」10 项为原站实测（未登录可见）；「代码开发」为按同构补充，原站需登录后才渲染完整分组
SCENES: dict[str, list[str]] = {
    "日常办公": ["幻灯片", "视频生成", "深度研究", "文档处理", "数据分析",
                 "可视化", "金融服务", "产品管理", "设计", "邮件编辑"],
    "代码开发": ["代码补全", "重构建议", "单元测试", "代码审查", "Bug 定位",
                 "接口联调", "性能分析", "SQL 优化"],
}

SYSTEM_PROMPT = (
    "你是 MiniYuxi 工作台的助手。回答需简洁、结构化，优先使用给定的资料片段；"
    "资料未覆盖时明确说明，不要编造数字与结论。"
)


def _build_system_prompt(
    mode: str = "agent",
    allow_full_access: bool = True,
    expert: str | None = None,
    skill: str | None = None,
    connector_ids: list[str] | None = None,
) -> str:
    """根据左侧功能区状态构造系统提示。"""
    parts = [SYSTEM_PROMPT]

    mode = (mode or "agent").lower()
    if mode == "ask":
        parts.append("当前模式：仅问答。请直接回答用户问题，不要调用工具，不要生成执行计划。")
    elif mode == "plan":
        parts.append(
            "当前模式：计划。请只输出一份可执行的分步骤计划（用 1./2./3. 编号），"
            "说明每一步的目的、所需信息和预期输出；不要执行工具，不要直接给出最终答案。"
        )
    else:
        parts.append(
            "当前模式：Agent。请主动分析任务、自主规划步骤、必要时调用工具完成目标，"
            "并在最后给出清晰结论。"
        )

    if not allow_full_access:
        parts.append(
            "【安全限制】当前未开启「允许完全访问」。你只能读取、查询、总结信息，"
            "禁止调用写入、删除、执行命令、发送消息、修改配置等会改变系统状态或产生外部副作用的工具。"
        )

    if expert:
        parts.append(f"当前专家角色：{expert}。请按该专家角色风格作答。")

    if skill:
        parts.append(f"当前调用的 Skill：{skill}。请优先按该 Skill 的方法论处理。")

    if connector_ids:
        parts.append(f"可用连接器：{', '.join(connector_ids)}。必要时可说明需要哪个连接器获取数据。")

    return "\n\n".join(parts)


def _fetch_attached_context(tenant_id: str, doc_ids: list[str]) -> str:
    from . import rag
    chunks = []
    for did in doc_ids:
        try:
            title = "未命名"
            docs = rag.list_documents(tenant_id) or []
            for d in docs:
                if d.get("id") == did:
                    title = d.get("title") or did
                    break
            text = rag.get_document_text(tenant_id, did, max_chars=4000)
            if text:
                chunks.append(f"【已附加文档：{title}】\n{text}")
        except Exception:
            pass
    return "\n\n".join(chunks) if chunks else ""


def _conn():
    """私有连接：不复用 db.connect() 的线程级缓存连接，避免因 close() 污染共享连接
    （db.py 的 connect() 返回线程级单例，被任意模块 close 后会殃及同线程后续请求）。"""
    import sqlite3
    from . import config
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init(conn=None) -> None:
    """建表（幂等）。被 api.py 启动块调用。

    注意：不关闭 db.connect() 返回的线程级共享连接（尤其主事件循环线程），
    否则后续同线程的 async 端点（如 /api/kb/upload）会拿到已关闭的连接。
    """
    c = conn or db.connect()
    c.execute(TABLE_SQL)
    c.commit()


def bootstrap(tenant_id: str = "default") -> dict:
    """复刻页初始化数据。"""
    from . import rag

    doc_count = 0
    try:
        doc_count = len(rag.list_documents(tenant_id) or [])
    except Exception:
        doc_count = 0

    return {
        "ok": True,
        "nav": NAV_ITEMS,
        "scenes": SCENES,
        "overview": [
            {"key": "知识库文档", "val": doc_count, "pct": min(100, doc_count * 4)},
            {"key": "场景分组", "val": len(SCENES), "pct": 100},
            {"key": "后端模式", "val": _backend_mode(), "pct": 100},
        ],
    }


def _backend_mode() -> str:
    """判定当前 LLM 后端是否可用，供前端展示降级状态。"""
    from . import gateway

    try:
        if getattr(gateway, "chat", None):
            return "在线"
    except Exception:
        pass
    return "降级"


def log_event(tenant_id: str, event: str, scene: str = "", payload: Any = None) -> None:
    try:
        conn = _conn()
        conn.execute(
            "INSERT INTO wb_replica_events (tenant_id, event, scene, payload, ts) VALUES (?,?,?,?,?)",
            (tenant_id, event, scene, json.dumps(payload or {}, ensure_ascii=False), time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def chat(tenant_id: str, message: str, scene: str = "",
         history: list[dict] | None = None, provider: str | None = None,
         model: str | None = None, mode: str = "agent",
         allow_full_access: bool = True, expert: str | None = None,
         skill: str | None = None, connector_ids: list[str] | None = None,
         attached_doc_ids: list[str] | None = None,
         model_id: str = "", strategy: str = "balanced") -> dict:
    """复刻页对话。

    model_id 形如 `siliconflow:Qwen/Qwen2.5-72B-Instruct`；非空时走多模型中枢 model_hub，
    为空时按 strategy 自动路由（亦经 model_hub），否则回落到原 gateway 通道。
    返回：{"ok":bool,"reply":str,"sources":list,"degraded":bool,"err":str}
    degraded=True 表示 LLM/检索不可用，回复为降级占位文本。
    """
    from . import rag, experts as experts_mod

    message = (message or "").strip()
    if not message:
        return {"ok": False, "reply": "", "sources": [], "degraded": True, "err": "empty message"}

    sources: list[dict] = []
    context = ""
    try:
        hits = rag.search(tenant_id, message, top_k=4) or []
        for h in hits:
            sources.append({
                "title": h.get("title", ""),
                "url": h.get("doc_id", ""),
                "snippet": (h.get("text") or "")[:160],
            })
        if hits:
            context = "\n\n".join(
                f"[{i+1}] {h.get('title','')}\n{(h.get('text') or '')[:500]}"
                for i, h in enumerate(hits)
            )
    except Exception:
        sources, context = [], ""

    # 专家信息
    expert_name = expert or ""
    if expert and not expert_name.startswith("当前专家"):
        e_obj = experts_mod.get_expert(expert, tenant_id)
        if e_obj:
            expert_name = f"{e_obj.get('name','')}（{e_obj.get('description','')}）"

    # 构造动态 system prompt
    system = _build_system_prompt(
        mode=mode,
        allow_full_access=allow_full_access,
        expert=expert_name,
        skill=skill,
        connector_ids=connector_ids or [],
    )

    prompt = message
    parts = []
    attached = _fetch_attached_context(tenant_id, attached_doc_ids or [])
    if attached:
        parts.append(attached)
    if context:
        parts.append(context)
    if parts:
        prompt = "参考资料：\n" + "\n\n".join(parts) + "\n\n问题：" + message

    reply = ""
    ok = False
    err = ""
    routed = None
    try:
        if model_id or strategy:
            # 走多模型中枢：手动指定优先，否则按策略自动路由
            from . import model_hub
            routed = model_hub.route(message, strategy) if not model_id else \
                {"model_id": model_id, "model_name": model_id, "task_type": model_hub.classify(message)["task_type"],
                 "name": model_hub.classify(message)["name"], "reason": "手动指定"}
            r = model_hub.chat(routed["model_id"], system, prompt, history or [], tenant_id) or {}
            ok = bool(r.get("ok"))
            reply = (r.get("text") or "").strip()
            err = r.get("err") or ""
            routed = {**routed, "latency_ms": r.get("latency_ms", 0),
                      "cost": r.get("cost", 0), "tokens": r.get("tokens", 0),
                      "model_name": r.get("model_name", routed.get("model_name", ""))}
        else:
            r = rag.llm_chat(system, prompt, history=history or [], tenant_id=tenant_id,
                             provider=provider, model=model) or {}
            ok = bool(r.get("ok"))
            reply = (r.get("text") or "").strip()
            err = r.get("err") or ""
    except Exception as e:  # 任何异常都降级，不把 500 抛给前端
        ok, reply, err = False, "", f"{type(e).__name__}: {e}"

    degraded = not ok or not reply
    if degraded:
        reply = (
            "【后端降级回复】未取得模型输出"
            + (f"（{err}）" if err else "")
            + "。\n\n你输入的是：" + message + "\n"
            + ("\n已检索到 " + str(len(sources)) + " 条知识库片段，见「引用来源」。"
               if sources else "\n知识库未命中相关片段。")
        )

    log_event(tenant_id, "chat", scene, {"len": len(message), "ok": ok, "src": len(sources), "mode": mode})
    return {"ok": ok, "reply": reply, "sources": sources, "degraded": degraded, "err": err,
            "mode": mode, "routed": routed}


def stats(tenant_id: str = "default") -> dict:
    """复刻页事件统计（轻量）。"""
    try:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM wb_replica_events WHERE tenant_id=?", (tenant_id,)
            ).fetchone()
            # 先取值再关闭：sqlite3.Row 在连接关闭后不可再取列
            n = row["n"] if row else 0
        finally:
            conn.close()
        return {"ok": True, "events": n}
    except Exception as e:
        return {"ok": False, "events": 0, "err": str(e)}
