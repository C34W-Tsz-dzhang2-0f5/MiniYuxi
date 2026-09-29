"""MCP 工具层（T2）：Python 工具自注册表（抄 Hermes ToolRegistry 自注册）+ 内置工具。

内置工具零依赖（current_time / calc / kb_search / count_docs）。外部 MCP 工具经 mcp_client 懒连接注册。
运行时建 tools_registry 表（绕开冻结 db.py），持久化工具元信息以便 /api/tools/list 读取。
"""
import ast
import datetime
import json
import os
import time
from . import db

_REGISTRY = {}  # name -> {name, description, schema, toolset, handler}


def tool(name, description, schema=None, toolset="builtin", requires_approval=False):
    def deco(fn):
        _REGISTRY[name] = {
            "name": name, "description": description,
            "schema": schema or {}, "toolset": toolset, "handler": fn,
            "requires_approval": requires_approval,
        }
        return fn
    return deco


# ---------------- 内置工具（零依赖）----------------
@tool("current_time", "返回当前日期与时间",
      {"type": "object", "properties": {}}, "builtin")
def _t(tenant_id=None, **_):
    now = datetime.datetime.now()
    return {"result": now.strftime("%Y-%m-%d %H:%M:%S %A"), "note": "本地时间"}


@tool("calc", "安全计算算术表达式，如 123*456+7",
      {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}, "builtin")
def _calc(expression, tenant_id=None, **_):
    try:
        node = ast.parse(expression, mode="eval")
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Load,
                   ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.FloorDiv)
        for n in ast.walk(node):
            if not isinstance(n, allowed):
                raise ValueError("不支持的运算符")
        val = eval(compile(node, "<calc>", "eval"))
        return {"result": str(val), "expression": expression}
    except Exception as e:
        return {"error": f"计算失败：{e}"}


@tool("kb_search", "在企业知识库内检索并返回命中片段",
      {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, "builtin")
def _kb(query, tenant_id=None, **_):
    from . import rag
    hits = rag.search(tenant_id or "default", query, 3)
    if not hits:
        return {"result": "知识库未检索到相关内容"}
    return {"result": "\n".join(f"[{i+1}] {h['title']}: {h['text'][:160]}" for i, h in enumerate(hits))}


@tool("count_docs", "统计当前知识库文档数量",
      {"type": "object", "properties": {}}, "builtin")
def _count(tenant_id=None, **_):
    n = db.connect().execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    return {"result": f"知识库共有 {n} 份文档"}


# ---------------- 联网搜索（T2 真实搜索，零依赖）----------------
# 联网类工具的可选审批门：默认关闭（保持 Agent 自动化流畅）。
# 设 MINIYUXI_APPROVE_WEB_SEARCH=1 后，web_search 每次调用都挂起 HITL 审批卡，
# 用于需要管控「对外查询内容/出口流量」的企业场景。
_WEB_SEARCH_APPROVAL = os.getenv("MINIYUXI_APPROVE_WEB_SEARCH", "").strip().lower() in (
    "1", "true", "yes", "on",
)


@tool("web_search", "联网搜索实时信息（新闻 / 天气 / 百科 / 最新动态等）。参数 query 为搜索关键词。",
      {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
      "builtin", requires_approval=_WEB_SEARCH_APPROVAL)
def _web_search(query, tenant_id=None, **_):
    """零依赖真实联网搜索：标准库 urllib 直连，无需额外 Key。
    优先级：① 企业搜索后端(WEB_SEARCH_API_URL+KEY) → ② Bing(cn/www，国内可达) → ③ DuckDuckGo(兜底) → 友好降级。
    DuckDuckGo 在部分网络环境（如中国大陆）不可达，故默认走 Bing。"""
    # 出境闸门：搜索词由用户问题派生，属「数据出境」的一类。
    # 被拒 → 返回友好降级文案，不崩链路。
    from . import egress
    if egress.blocked("search", "web_search", query, tenant_id=tenant_id):
        return {"result": "（联网检索已被数据出境策略拒绝。请联系管理员调整「数据出境」策略。）"}
    import html as _html
    import re as _re
    import urllib.parse as _up
    import urllib.request as _ur

    def _strip(s):
        s = _html.unescape(s or "")
        return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", "", s)).strip()

    def _fetch(url, timeout=10):
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with _ur.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")

    def _bing_items(html):
        items = []
        for blk in html.split('<li class="b_algo"')[1:6]:
            seg = blk.split("</li>")[0]
            mt = _re.search(r"<h2>.*?<a[^>]*>(.*?)</a>", seg, _re.S)
            title = _strip(mt.group(1)) if mt else ""
            ms = (_re.search(r'<p class="[^"]*b_lineclamp[^"]*">(.*?)</p>', seg, _re.S)
                  or _re.search(r"<p[^>]*>(.*?)</p>", seg, _re.S))
            snippet = _strip(ms.group(1)) if ms else ""
            if title or snippet:
                items.append(f"{title}\n  {snippet}")
        return items

    # ① 企业级搜索后端（火山引擎/豆包 联网搜索，中文更准）
    #    兼容两种配置：显式 WEB_SEARCH_API_URL+WEB_SEARCH_API_KEY，或复用 DOUBAO_API_KEY(+DOUBAO_BASE_URL，与 doubao-search MCP 同密钥)。
    def _doubao_items(base_url, key):
        url = base_url if "/search_api" in base_url else f"{base_url.rstrip('/')}/search_api/web_search"
        body = json.dumps({"Query": query, "SearchType": "web", "Count": 8, "NeedSummary": True}).encode("utf-8")
        req = _ur.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "X-Traffic-Tag": "web_search_mcp",
        })
        with _ur.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        cand = data.get("Result", data)
        results = ((cand.get("WebResults") if isinstance(cand, dict) else None)
                   or data.get("Results") or data.get("results") or data.get("data") or [])
        out = []
        for it in results[:8]:
            title = it.get("Title") or it.get("title") or ""
            snippet = it.get("Summary") or it.get("Snippet") or it.get("Content") or it.get("snippet") or it.get("content") or ""
            link = it.get("Url") or it.get("url") or ""
            if title or snippet:
                out.append(f"{title}\n  {link}\n  {snippet}")
        return out

    backend = (os.getenv("SEARCH_BACKEND", "doubao") or "doubao").lower()

    # ① 企业级搜索后端（火山引擎/豆包 联网搜索，中文更准）—— 默认后端
    if backend in ("doubao",):
        ent_url = os.getenv("WEB_SEARCH_API_URL", "").strip()
        ent_key = os.getenv("WEB_SEARCH_API_KEY", "").strip()
        if not (ent_url and ent_key):
            ent_key = os.getenv("DOUBAO_API_KEY", "").strip()
            ent_url = os.getenv("DOUBAO_BASE_URL", "https://open.feedcoopapi.com").strip()
        if ent_url and ent_key:
            try:
                items = _doubao_items(ent_url, ent_key)
                if items:
                    return {"result": "联网搜索结果（企业搜索后端 · 豆包/火山引擎）：\n" + "\n\n".join(items)}
            except Exception:
                pass

    # ② Bing（国内可达，cn 优先）
    if backend in ("doubao", "bing"):
        q = _up.quote(query)
        for host in ("cn.bing.com", "www.bing.com"):
            try:
                html = _fetch(f"https://{host}/search?q={q}&setlang=zh-CN&cc=CN")
                items = _bing_items(html)
                if items:
                    return {"result": "联网搜索结果（Bing）：\n" + "\n\n".join(items)}
            except Exception:
                continue

    # ③ DuckDuckGo 兜底
    if backend in ("doubao", "bing", "duckduckgo"):
        try:
            html = _fetch(f"https://html.duckduckgo.com/html/?q={q}", timeout=12)
            items = [f"{_strip(t)}\n  {_strip(s)}" for t, s in
                     _re.findall(r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', html, _re.S)[:5]]
            if items:
                return {"result": "联网搜索结果（DuckDuckGo）：\n" + "\n\n".join(items)}
        except Exception:
            pass

    return {"result": "（当前环境无法联网检索，可能受网络出口限制。可配置 WEB_SEARCH_API_URL+WEB_SEARCH_API_KEY 走企业搜索后端。）"}


# health 后端探测缓存：/api/health 是热端点，避免每次真实网络探测（超时可达 4s）。
_SB_STATUS_TTL = 30.0
_sb_status_cache = {"ts": 0.0, "val": None}


def search_backend_status():
    """返回当前 web_search 的默认/生效后端信息，供 /api/health 前端展示。

    真实探测豆包(火山引擎)是否可达，让“已激活为默认搜索”可被一眼确认。
    结果带 TTL 缓存（默认 30s），避免每次 /api/health 都发起阻塞式网络探测。"""
    global _sb_status_cache
    now = time.time()
    if _sb_status_cache["val"] is not None and now - _sb_status_cache["ts"] < _SB_STATUS_TTL:
        return _sb_status_cache["val"]
    backend = (os.getenv("SEARCH_BACKEND", "doubao") or "doubao").lower()
    ent_url = os.getenv("WEB_SEARCH_API_URL", "").strip()
    ent_key = os.getenv("WEB_SEARCH_API_KEY", "").strip()
    if not (ent_url and ent_key):
        ent_key = os.getenv("DOUBAO_API_KEY", "").strip()
        ent_url = os.getenv("DOUBAO_BASE_URL", "https://open.feedcoopapi.com").strip()
    configured = bool(ent_url and ent_key)
    reachable = None
    if configured and backend in ("doubao",):
        from . import egress
        # 探针载荷是固定常量 "ping"（无用户数据），但**仍受策略约束**：
        # 企业要求「零外发」时这里必须直接判定不可达，不能偷偷打外网。
        # audit=False：30s 一次的高频探针不写审计行，避免把出境日志灌成噪音。
        if egress.blocked("search", ent_url, "ping", audit=False):
            reachable = False
        else:
            try:
                import urllib.request as _ur
                url = ent_url.rstrip("/") + ("/search_api/web_search" if "/search_api" not in ent_url else "")
                req = _ur.Request(
                    url,
                    data=json.dumps({"Query": "ping", "SearchType": "web", "Count": 1, "NeedSummary": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json",
                              "Authorization": f"Bearer {ent_key}",
                              "X-Traffic-Tag": "web_search_mcp"},
                )
                with _ur.urlopen(req, timeout=4) as r:
                    reachable = (r.status == 200)
            except Exception:
                reachable = False
    labels = {"doubao": "豆包/火山引擎", "bing": "Bing", "duckduckgo": "DuckDuckGo"}
    chain = (["doubao", "bing", "duckduckgo"] if backend == "doubao"
             else [backend, "duckduckgo"] if backend == "bing" else [backend])
    result = {
        "default": backend,
        "default_label": labels.get(backend, backend),
        "enterprise_configured": configured,
        "enterprise_reachable": reachable,
        "fallback_chain": chain,
    }
    _sb_status_cache["val"] = result
    _sb_status_cache["ts"] = now
    return result


# ---------------- 注册表操作 ----------------
def register(name, description, schema, toolset, handler, risk="info", requires_approval=False):
    """供外部（MCP）动态注册工具。

    risk: info / warn / critical —— 工具风险等级（驱动前端/审计展示）。
    requires_approval: 是否强制 HITL 审批（run_tool_governed 自动挂审批卡）。
    """
    _REGISTRY[name] = {"name": name, "description": description, "schema": schema,
                       "toolset": toolset, "handler": handler,
                       "risk": risk, "requires_approval": bool(requires_approval)}


def unregister(name):
    """移除已注册工具（供 Coding Agent 自生成工具回收使用）。"""
    _REGISTRY.pop(name, None)


def call_tool(name, args=None, tenant_id=None):
    spec = _REGISTRY.get(name)
    if not spec:
        return {"error": f"未知工具：{name}"}
    # 执行层安全兜底（Hermes 十一·hardline block / path security）：
    # 任何字符串参数若命中不可恢复命令黑名单，直接 fail-closed 拦截，
    # 不走审批、不依赖提示词约束。覆盖 agent_loop 与 api.py 两条执行路径。
    try:
        from . import security
        for v in (args or {}).values():
            if isinstance(v, str) and security.hardline_block(v):
                return {"error": "执行被安全层拦截：命中不可恢复命令黑名单（hardline block）"}
    except Exception:
        pass
    try:
        res = spec["handler"](tenant_id=tenant_id, **(args or {}))
        return {"name": name, "toolset": spec["toolset"], "result": res}
    except Exception as e:
        return {"error": str(e)}


def _audit_tool_event(tool_name: str, result: str, severity: str = "info",
                      tenant_id=None, session_id=None, detail=None) -> None:
    """工具调用审计留痕 —— 安全分层的最后一环（Hermes 原则⑪：audit）。

    hardline 拦截 / 审批 / 路径校验 已在 B-1、B-5 落地，这里补齐审计，
    使每次工具调用（含被拒绝、被拦截、被挂起）都可追溯。

    审计失败静默降级：审计不可用不应阻断工具执行主流程。
    """
    try:
        from . import soc_audit

        soc_audit.log({
            "tenant_id": tenant_id or "default",
            "actor": session_id or "agent",
            "role": "agent",
            "action": "tool.call",
            "target": tool_name,
            "result": result,
            "severity": severity,
            "session_id": session_id or "",
            "detail": detail or {},
        })
    except Exception:
        pass


def run_tool_governed(name, args=None, tenant_id=None, session_id=None, approved_aid=None):
    """治理版工具调用（对应 Hermes 三·工具治理管线 + 十一·审批门）。

    顺序：未知工具 → 安全兜底(hardline) → 续跑分支(已批准审批单) → 审批门(requires_approval / 命门工具) → 执行。
    每个出口都写审计留痕（result: rejected / blocked / pending / resumed / success / error）。
    命中审批门时不执行，返回 {status:'pending', approval_id} 由上层挂起等待 HITL 决策。
    approved_aid：HITL 闭环续跑凭证——前端在 /api/approvals/{aid}/decide 通过后，
    再次调用并带上已 approved 的 aid，此处跳过审批门直接执行（不重复建单、不绕过 hardline）。
    """
    spec = _REGISTRY.get(name)
    if not spec:
        _audit_tool_event(name, "rejected", "warn", tenant_id, session_id,
                          {"reason": "unknown tool"})
        return {"error": f"未知工具：{name}"}
    # 安全兜底先行
    try:
        from . import security
        for v in (args or {}).values():
            if isinstance(v, str) and security.hardline_block(v):
                _audit_tool_event(name, "blocked", "critical", tenant_id, session_id,
                                  {"reason": "hardline block", "args": str(args)[:500]})
                return {"error": "执行被安全层拦截：命中不可恢复命令黑名单（hardline block）"}
    except Exception:
        pass
    # 续跑分支：带上已 approved 的审批单时，跳过审批门直接执行（HITL 闭环）。
    # 仍保留上方 hardline 安全兜底——续跑也不绕过不可恢复命令拦截。
    if approved_aid:
        try:
            from . import approval
            ap = approval.get(approved_aid)
            if ap and ap.get("status") == "approved":
                _audit_tool_event(name, "resumed", "info", tenant_id, session_id,
                                  {"approval_id": approved_aid})
                # B2 防御纵深：高危/需确认工具仅在 HITL 续跑时注入 __commit=True，
                # Adapter 才真正提交业务单据（首次未经审批的调用被上方审批门拦截，
                # 即便绕过也只会落到 Adapter 的“预览态”，不会直提交）。
                if spec.get("requires_approval") or spec.get("risk") == "high_risk":
                    args = dict(args or {})
                    args["__commit"] = True
                return call_tool(name, args, tenant_id=tenant_id)
            # 未批准 / 已拒绝 / 不存在 → 落到下方审批门重新评估，避免绕过审批门
        except Exception:
            pass
    # 审批门：工具自身标记 或 落入命门/风险集合
    try:
        from . import approval
        if spec.get("requires_approval") or approval.needs_approval(name):
            aid = approval.create(
                tenant_id or "default", name,
                args_json=json.dumps(args or {}, ensure_ascii=False),
                requested_by=session_id or "", risk="high",
            )
            _audit_tool_event(name, "pending", "warn", tenant_id, session_id,
                              {"approval_id": aid})
            return {"status": "pending", "approval_id": aid, "tool_name": name}
    except Exception:
        pass
    # 执行并审计结果
    try:
        res = call_tool(name, args, tenant_id=tenant_id)
    except Exception as exc:  # noqa: BLE001
        _audit_tool_event(name, "error", "error", tenant_id, session_id,
                          {"error": str(exc)[:300]})
        raise
    failed = isinstance(res, dict) and bool(res.get("error"))
    _audit_tool_event(name, "error" if failed else "success",
                      "error" if failed else "info", tenant_id, session_id,
                      {"args": str(args)[:500]})
    return res


# MCP 工具发现结果缓存：避免每次 /api/tools/list（UI 加载必调）都做外部网络探测。
_MCP_DISCOVER_TTL = 60.0
_mcp_discover_cache = {"ts": 0.0, "val": []}


def invalidate_mcp_cache():
    """前端添加/变更 mcp 连接器后，强制下一轮 /api/tools/list 重新做 SSE 发现。"""
    _mcp_discover_cache["ts"] = 0.0


def list_tools() -> list:
    base = [{"name": v["name"], "description": v["description"], "schema": v["schema"],
             "toolset": v["toolset"], "risk": v.get("risk", "info"),
             "requires_approval": bool(v.get("requires_approval", False))}
            for v in _REGISTRY.values()]
    try:
        from . import mcp_client
        now = time.time()
        if now - _mcp_discover_cache["ts"] > _MCP_DISCOVER_TTL:
            local = mcp_client.discover_tools()
            remote = mcp_client.discover_connector_tools()
            _mcp_discover_cache["val"] = local + remote
            _mcp_discover_cache["ts"] = now
        base += _mcp_discover_cache["val"]
    except Exception:
        pass
    return base


def tool_inventory_text() -> str:
    """可用工具的自然语言清单（供系统提示注入）。

    与 function calling 的 schema 互补：schema 告诉模型「参数怎么填」，这里告诉它
    「有哪些能力可用、必须真正调用」。缺了这一段，模型只会把工具当成给用户讲解的
    命令——表现为「装技能装不了 / 写代码写不了」。
    """
    lines = []
    try:
        for t in list_tools():
            desc = (t.get("description") or "").strip()
            mark = "（需审批）" if t.get("requires_approval") else ""
            lines.append(f"- {t.get('name')}：{desc}{mark}")
    except Exception:
        return ""
    return "\n".join(lines)


def init():
    try:
        conn = db.connect()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tools_registry(
                name TEXT PRIMARY KEY, toolset TEXT, description TEXT, schema TEXT, enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')))"""
        )
        # ---- T2+「本地工具市场」（抄 treg 理念 · 本地化）：补元数据列 + 索引 ----
        for col, decl in [
                    ("category", "TEXT DEFAULT 'utility'"),       # utility / knowledge / web / mcp / skill / user ...
                    ("tags", "TEXT DEFAULT '[]'"),                # JSON 数组
                    ("risk", "TEXT DEFAULT 'info'"),               # info / warn / critical
                    ("source", "TEXT DEFAULT 'builtin'"),         # builtin / mcp / user / skill
                    ("requires_approval", "INTEGER DEFAULT 0"),
                    # ⚠️ 必须用「常量」默认值：ALTER TABLE ADD COLUMN 不允许非常量默认
                    # （写 DEFAULT (datetime('now')) 会报 "Cannot add a column with non-constant default"，
                    #  导致该列永远加不上 → 所有 SET updated_at=... 的 UPDATE 全部静默失败）。
                    ("updated_at", "TEXT DEFAULT ''"),
                ]:
            try:
                conn.execute("ALTER TABLE tools_registry ADD COLUMN %s %s" % (col, decl))
            except Exception:
                pass  # 列已存在，ALTER 会报错，吞掉即可（幂等）
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_registry_cat ON tools_registry(category, enabled)")
        conn.commit()
        for v in _REGISTRY.values():
            conn.execute(
                "INSERT OR IGNORE INTO tools_registry(name,toolset,description,schema) VALUES(?,?,?,?)",
                (v["name"], v["toolset"], v["description"], json.dumps(v["schema"], ensure_ascii=False)),
            )
        # 回填元数据：只刷「尚未回填」的行（以 tags 为空判定），
        # 避免每次启动都覆盖运营手动维护过的分类/风险等级。
        for name, cat, tags, risk, src, ra in _BUILTIN_META:
            try:
                conn.execute(
                    "UPDATE tools_registry SET category=?, tags=?, risk=?, source=?, requires_approval=?, "
                    "updated_at=datetime('now') "
                    "WHERE name=? AND (tags IS NULL OR tags='' OR tags='[]')",
                    (cat, json.dumps(tags, ensure_ascii=False), risk, src, 1 if ra else 0, name),
                )
            except Exception:
                pass
        conn.commit()
    except Exception:
        pass


# 内置工具的市场元数据（与 @tool() 注册同步；此表只供 init 回填用，不参与运行）
_BUILTIN_META = [
    # name,              category,    tags,                risk,     source,   requires_approval
    ("current_time",      "utility",   ["time", "builtin"], "info",   "builtin", False),
    ("calc",              "utility",   ["math", "builtin"], "info",   "builtin", False),
    ("kb_search",         "knowledge", ["rag", "internal"], "info",   "builtin", False),
    ("count_docs",        "knowledge", ["rag", "stats"],    "info",   "builtin", False),
    ("web_search",        "web",        ["network", "search"], "warn", "builtin", True),
]


# ---------------- 本地工具市场（抄 treg 理念 · 本地化 · 不接任何远端凭据）----------------
def list_market(category: str = "", tag: str = "", q: str = "", enabled_only: bool = False) -> list:
    """市场视角的工具列表：分类/标签/关键词筛选。

    合规：纯本地查询 SQLite + 内存注册表；不触发任何外部网络探测。
    远端 MCP 工具的发现走 mcp_client.discover_tools()（本地进程），仍保留「source=mcp」。
    """
    where, params = [], []
    if category:
        where.append("category=?"); params.append(category)
    if enabled_only:
        where.append("enabled=1")
    where.append("(risk != '' OR category != '')")  # 已回填元数据的
    sql = (
        "SELECT name,toolset,description,schema,enabled,category,tags,risk,source,requires_approval "
        "FROM tools_registry"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY category ASC, name ASC"
    try:
        rows = db.connect().execute(sql, params).fetchall()
    except Exception:
        rows = []
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        try:
            d["schema"] = json.loads(d.get("schema") or "{}")
        except Exception:
            d["schema"] = {}
        d["requires_approval"] = bool(d.get("requires_approval"))
        d["enabled"] = bool(d.get("enabled"))
        if tag and tag not in d["tags"]:
            continue
        if q and (q not in (d["name"] or "") and q not in (d["description"] or "")):
            continue
        out.append(d)
    return out


def get_market(name: str):
    """取单个工具的完整市场详情。"""
    try:
        row = db.connect().execute(
            "SELECT name,toolset,description,schema,enabled,category,tags,risk,source,requires_approval "
            "FROM tools_registry WHERE name=?", (name,)
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    try:
        d["schema"] = json.loads(d.get("schema") or "{}")
    except Exception:
        d["schema"] = {}
    d["requires_approval"] = bool(d.get("requires_approval"))
    d["enabled"] = bool(d.get("enabled"))
    return d


def toggle_market(name: str, enabled: bool) -> bool:
    """切换工具启停（disabled 时 run_tool_governed 仍会拒绝调用）。返回是否命中。"""
    try:
        cur = db.connect().execute(
            "UPDATE tools_registry SET enabled=?, updated_at=datetime('now') WHERE name=?",
            (1 if enabled else 0, name),
        )
        db.connect().commit()
        return cur.rowcount > 0
    except Exception:
        return False


def list_categories() -> list:
    """返回已用到的 category 列表（按工具数量降序），便于前端抽屉做标签条。"""
    try:
        rows = db.connect().execute(
            "SELECT category, COUNT(*) AS n FROM tools_registry "
            "WHERE category != '' GROUP BY category ORDER BY n DESC"
        ).fetchall()
        return [{"category": r["category"], "count": r["n"]} for r in rows]
    except Exception:
        return []


# ---------------- 视频生成（V1）：经"视频 MCP 连接器"转发 ----------------
#  设计：MiniYuxi 自身不带视频模型。视频能力通过连接器挂一个 capability=video 的 MCP
#  服务实现（连接器框架已支持任意 MCP 工具的发现与调用）。本工具负责：解析该连接器 →
#  发现其视频生成工具 → 转发 prompt。未配置时返回明确接入指引（不崩、不误导）。
@tool(
    "video.generate",
    "生成视频：通过已配置的视频 MCP 连接器转发到视频生成服务；若未配置则提示如何接入。",
    {"type": "object",
     "properties": {"prompt": {"type": "string", "description": "视频内容描述 / 分镜脚本"}},
     "required": ["prompt"]},
    "video", requires_approval=False,
)
def _video_generate(tenant_id=None, **args):
    prompt = args.get("prompt") or ""
    if not prompt:
        return {"error": "缺少 prompt 参数（视频内容描述/脚本）"}
    try:
        from . import connectors
        from . import mcp_client
        target = None
        for d in connectors.list_connectors():
            if d.get("kind") != "mcp" or not d.get("enabled"):
                continue
            cfg = json.loads(d.get("config_json") or "{}")
            if cfg.get("capability") == "video" or cfg.get("video"):
                target = (d["id"], cfg)
                break
        if not target:
            return {"error": "未配置视频服务商：请在「连接器」中添加一个 kind=mcp、transport=sse、"
                            "config.capability='video' 的 MCP 连接器（指向你的视频生成服务），再调用本工具。"}
        cid, cfg = target
        endpoint = cfg.get("endpoint")
        if not endpoint:
            return {"error": "视频连接器缺少 endpoint"}
        token = mcp_client._resolve_token(cfg)
        cli = mcp_client.MCPClientSSE(endpoint, token=token, timeout=30.0)
        cli.initialize()
        tools = cli.list_tools()
        cli.close()
        vtool = cfg.get("video_tool")
        if not vtool:
            for t in tools:
                nm = (t.get("name") or "").lower()
                if "video" in nm or "生成视频" in nm or "text_to_video" in nm or "t2v" in nm:
                    vtool = t.get("name")
                    break
        if not vtool:
            names = ", ".join((t.get("name") or "") for t in tools) or "（无）"
            return {"error": "该视频 MCP 未暴露视频生成工具（名称应含 video/t2v）。已发现：" + names}
        cli2 = mcp_client.MCPClientSSE(endpoint, token=token, timeout=90.0)
        cli2.initialize()
        payload = {"prompt": prompt}
        for k, v in args.items():
            if k != "prompt":
                payload[k] = v
        res = cli2.call_tool(vtool, payload)
        cli2.close()
        return res or {}
    except Exception as e:
        return {"error": "视频生成调用失败：" + str(e)[:200]}


# ---------------- 技能管理（T6 闭环 · 对话内可执行）----------------
#  背景（2026-09-29 阿长反馈）：技能安装此前只有「UI 抽屉」和 HTTP 接口两条入口，
#  **没有注册成工具** → 用户在对话框里说「装这个技能 / npx skills add <url>」时，
#  Agent Loop 的工具清单里根本没有对应能力，模型只能把命令"解释"一遍，不会真的执行。
#  这里把 core/skills_install 的三件事暴露成工具，让「自然语言 → 真执行」闭环成立。
#
#  审批门：与 web_search 同款 env 开关，默认关闭（保持自动化流畅）；
#  设 MINIYUXI_APPROVE_SKILL_INSTALL=1 后每次装/卸都挂 HITL 审批卡（企业管控场景）。
#  注：技能正文只作提示词注入、**不执行代码**（见 core/wb_workbench.py），
#      且 install_skill 内部已过 core.security（hardline / 危险命令 / 路径越界）+ 仅收 https。
_SKILL_APPROVAL = os.getenv("MINIYUXI_APPROVE_SKILL_INSTALL", "").strip().lower() in (
    "1", "true", "yes", "on",
)


def _guess_skill_method(source: str) -> str:
    """把「来源字符串」判成 install_skill 需要的 method：url / path / paste。

    判定顺序很重要：先看像不像链接，再看本地目录，最后才当正文——
    否则一段含 'http' 的 SKILL.md 正文会被误判成 URL。
    """
    s = (source or "").strip()
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://") or low.startswith("github.com/") \
            or low.endswith(".git") or low.startswith("git@"):
        return "url"
    if os.path.isdir(s):
        return "path"
    return "paste"


@tool(
    "skill.install",
    "安装技能（SKILL.md）到平台，让 Agent 获得新的工作手册/能力。"
    "触发场景：用户给出 GitHub 仓库地址、本地文件夹路径、或直接粘贴 SKILL.md 内容并要求「装/安装/添加技能」；"
    "也用于把 `npx skills add <仓库地址> --skill <名字>` 这类命令真正执行掉"
    "（此时 source=仓库地址，select=--skill 后面的名字）。"
    "**用户要求安装技能时必须调用本工具执行，不要只解释命令或给出手工步骤。**",
    {"type": "object",
     "properties": {
         "source": {"type": "string",
                    "description": "技能来源：https 仓库地址（如 https://github.com/owner/repo）、"
                                   "本地文件夹绝对路径、或 SKILL.md 全文"},
         "name": {"type": "string",
                  "description": "技能名（可选，仅字母数字_-.）。单个技能仓库用它覆盖 SKILL.md 里的 name；"
                                 "集合仓库（根目录无 SKILL.md）且未指定 select 时，用作容器目录名"},
         "select": {"type": "string",
                    "description": "只安装集合仓库里的某一个技能（可选，仅字母数字_-.）。"
                                   "对应 `npx skills add <仓库> --skill <名字>` 里的 --skill 值；"
                                   "命中则只装那一个，未命中会返回可用技能列表"},
         "method": {"type": "string", "enum": ["auto", "url", "path", "paste"],
                    "description": "来源类型；默认 auto 自动判断"},
     },
     "required": ["source"]},
    "skills", requires_approval=_SKILL_APPROVAL,
)
def _skill_install(source="", name="", select="", method="auto", tenant_id=None, **_):
    src = (source or "").strip()
    if not src:
        return {"error": "缺少 source 参数：请给出仓库地址 / 本地路径 / SKILL.md 内容"}
    m = (method or "auto").strip().lower()
    if m not in ("url", "path", "paste"):
        m = _guess_skill_method(src)
    try:
        from . import skills_install
        res = skills_install.install_skill(m, src, (name or "").strip(),
                                           select=(select or "").strip())
        if isinstance(res, dict) and res.get("ok"):
            res = dict(res)
            res["note"] = ("已安装并刷新技能目录，Agent 下一轮即可按 trigger 使用。"
                           "若该仓库是集合仓库（根目录无 SKILL.md），未指定 select 时整个仓库会"
                           "作为一个容器装入，其中的技能会被递归识别；"
                           "指定 select 时只装选中的那一个。")
        return res
    except Exception as e:  # SkillInstallError 也在此收敛为 error 字典，不抛栈
        return {"error": "技能安装失败：" + str(e)[:300]}


@tool(
    "skill.uninstall",
    "卸载已安装的技能（按技能名删除）。触发场景：用户说「卸载/删除/移除技能 xxx」。"
    "**必须调用本工具执行，不要只给出手工步骤。**",
    {"type": "object",
     "properties": {"name": {"type": "string", "description": "要卸载的技能名"}},
     "required": ["name"]},
    "skills", requires_approval=_SKILL_APPROVAL,
)
def _skill_uninstall(name="", tenant_id=None, **_):
    nm = (name or "").strip()
    if not nm:
        return {"error": "缺少 name 参数：请给出要卸载的技能名"}
    try:
        from . import skills_install
        return skills_install.uninstall_skill(nm)
    except Exception as e:
        return {"error": "技能卸载失败：" + str(e)[:300]}


@tool(
    "skill.list",
    "列出平台已安装的技能（名称 + 一句话说明）。触发场景：用户问「有哪些技能 / 装了哪些技能 / 技能列表」。",
    {"type": "object", "properties": {}}, "skills",
)
def _skill_list(tenant_id=None, **_):
    try:
        from . import skills_catalog
        items = [s for s in skills_catalog.list_skills() if s.get("name")]
        if not items:
            return {"result": "当前没有已安装的技能。可用 skill.install 从 GitHub 仓库或本地路径安装。"}
        lines = [f"- {s.get('name')}：{(s.get('description') or '').strip()[:60]}" for s in items[:80]]
        head = f"共 {len(items)} 个技能"
        if len(items) > 80:
            head += "（仅列出前 80 个）"
        return {"result": head + "：\n" + "\n".join(lines)}
    except Exception as e:
        return {"error": "读取技能列表失败：" + str(e)[:200]}
