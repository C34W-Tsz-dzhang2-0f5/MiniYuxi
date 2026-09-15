"""MCP 工具层（T2）：Python 工具自注册表（抄 Hermes ToolRegistry 自注册）+ 内置工具。

内置工具零依赖（current_time / calc / kb_search / count_docs）。外部 MCP 工具经 mcp_client 懒连接注册。
运行时建 tools_registry 表（绕开冻结 db.py），持久化工具元信息以便 /api/tools/list 读取。
"""
import ast
import datetime
import json
import os
from . import db

_REGISTRY = {}  # name -> {name, description, schema, toolset, handler}


def tool(name, description, schema=None, toolset="builtin"):
    def deco(fn):
        _REGISTRY[name] = {
            "name": name, "description": description,
            "schema": schema or {}, "toolset": toolset, "handler": fn,
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
@tool("web_search", "联网搜索实时信息（新闻 / 天气 / 百科 / 最新动态等）。参数 query 为搜索关键词。",
      {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, "builtin")
def _web_search(query, tenant_id=None, **_):
    """零依赖真实联网搜索：标准库 urllib 直连，无需额外 Key。
    优先级：① 企业搜索后端(WEB_SEARCH_API_URL+KEY) → ② Bing(cn/www，国内可达) → ③ DuckDuckGo(兜底) → 友好降级。
    DuckDuckGo 在部分网络环境（如中国大陆）不可达，故默认走 Bing。"""
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


def search_backend_status():
    """返回当前 web_search 的默认/生效后端信息，供 /api/health 前端展示。

    真实探测豆包(火山引擎)是否可达，让“已激活为默认搜索”可被一眼确认。"""
    backend = (os.getenv("SEARCH_BACKEND", "doubao") or "doubao").lower()
    ent_url = os.getenv("WEB_SEARCH_API_URL", "").strip()
    ent_key = os.getenv("WEB_SEARCH_API_KEY", "").strip()
    if not (ent_url and ent_key):
        ent_key = os.getenv("DOUBAO_API_KEY", "").strip()
        ent_url = os.getenv("DOUBAO_BASE_URL", "https://open.feedcoopapi.com").strip()
    configured = bool(ent_url and ent_key)
    reachable = None
    if configured and backend in ("doubao",):
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
    return {
        "default": backend,
        "default_label": labels.get(backend, backend),
        "enterprise_configured": configured,
        "enterprise_reachable": reachable,
        "fallback_chain": chain,
    }


# ---------------- 注册表操作 ----------------
def register(name, description, schema, toolset, handler):
    """供外部（MCP）动态注册工具。"""
    _REGISTRY[name] = {"name": name, "description": description, "schema": schema, "toolset": toolset, "handler": handler}


def unregister(name):
    """移除已注册工具（供 Coding Agent 自生成工具回收使用）。"""
    _REGISTRY.pop(name, None)


def call_tool(name, args=None, tenant_id=None):
    spec = _REGISTRY.get(name)
    if not spec:
        return {"error": f"未知工具：{name}"}
    try:
        res = spec["handler"](tenant_id=tenant_id, **(args or {}))
        return {"name": name, "toolset": spec["toolset"], "result": res}
    except Exception as e:
        return {"error": str(e)}


def list_tools() -> list:
    base = [{"name": v["name"], "description": v["description"], "schema": v["schema"], "toolset": v["toolset"]}
            for v in _REGISTRY.values()]
    try:
        from . import mcp_client
        base += mcp_client.discover_tools()
    except Exception:
        pass
    return base


def init():
    try:
        conn = db.connect()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tools_registry(
                name TEXT PRIMARY KEY, toolset TEXT, description TEXT, schema TEXT, enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')))"""
        )
        conn.commit()
        for v in _REGISTRY.values():
            conn.execute(
                "INSERT OR IGNORE INTO tools_registry(name,toolset,description,schema) VALUES(?,?,?,?)",
                (v["name"], v["toolset"], v["description"], json.dumps(v["schema"], ensure_ascii=False)),
            )
        conn.commit()
    except Exception:
        pass
