"""运行时热切换与多供应商路由（深度构造·项1）。

把 gateway 的"单 config 单例 + provider 形参空壳"升级为：
- 持久化供应商注册表（llm_providers 表）：可运行时增删供应商，不止 siliconflow/offline 两项；
- 运行时热切换：active_provider 存 kv_store，set_active() 即时生效，无需重启进程；
- 故障转移：主供应商 429/5xx/超时 → 自动切下一个 enabled 供应商 → 最终离线兜底；
- 离线兜底：无 Key 时返回 offline 信封，链路不崩。

不新增外部依赖（复用 requests）。所有调用走此路由，便于统一埋点与故障转移。
"""
import json
import time
import requests
from . import config, db, usage

MAX_RETRIES = 3
OFFLINE_ID = "offline"


def init(conn=None):
    c = conn or db.connect()
    c.execute("""CREATE TABLE IF NOT EXISTS llm_providers(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'openai',
        base_url TEXT NOT NULL, api_key TEXT NOT NULL DEFAULT '', model TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS kv_store(
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT DEFAULT (datetime('now')))""")
    c.commit()


def register_provider(provider: dict, conn=None):
    """provider: {id,name,kind,base_url,api_key,model,priority,enabled}。幂等。"""
    c = conn or db.connect()
    c.execute(
        "INSERT OR REPLACE INTO llm_providers(id,name,kind,base_url,api_key,model,priority,enabled) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (provider["id"], provider["name"], provider.get("kind", "openai"),
         provider["base_url"], provider.get("api_key", ""), provider["model"],
         int(provider.get("priority", 0)), 1 if provider.get("enabled", True) else 0),
    )
    c.commit()
    return provider["id"]


def list_providers(conn=None):
    c = conn or db.connect()
    rows = c.execute("SELECT * FROM llm_providers ORDER BY priority DESC, id").fetchall()
    return [dict(r) for r in rows]


def remove_provider(provider_id: str, conn=None):
    c = conn or db.connect()
    c.execute("DELETE FROM llm_providers WHERE id=?", (provider_id,))
    c.execute("DELETE FROM kv_store WHERE key='active_provider'")
    c.commit()


def set_active(provider_id: str, conn=None):
    """运行时热切换：即时生效，无需重启。"""
    c = conn or db.connect()
    row = c.execute("SELECT id,enabled FROM llm_providers WHERE id=?", (provider_id,)).fetchone()
    if not row:
        raise KeyError(f"provider not found: {provider_id}")
    c.execute("INSERT OR REPLACE INTO kv_store(key,value) VALUES('active_provider',?)", (provider_id,))
    c.commit()
    return provider_id


def get_active(conn=None):
    c = conn or db.connect()
    row = c.execute("SELECT value FROM kv_store WHERE key='active_provider'").fetchone()
    return row["value"] if row else None


def _provider_by_id(pid, conn):
    c = conn or db.connect()
    row = c.execute("SELECT * FROM llm_providers WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else None


def _enabled_ordered(conn):
    c = conn or db.connect()
    rows = c.execute("SELECT * FROM llm_providers WHERE enabled=1 ORDER BY priority DESC, id").fetchall()
    return [dict(r) for r in rows]


def _fallback_providers() -> list:
    """注册表为空时的环境变量回落（单供应商部署的默认路径）。

    llm_providers 表需要显式注册才有数据，而 config.LLM_PROVIDERS 一直带着
    LLM_API_KEY。agent_loop 改走本模块后若不做回落，未注册过的部署会全部退化为
    offline —— 表现为"明明配了 Key 却说离线"。故此处以 config 为单一可信源兜底。
    """
    out = []
    for p in (getattr(config, "LLM_PROVIDERS", None) or []):
        if not isinstance(p, dict):
            continue
        kind = p.get("kind", "openai")
        out.append({
            "id": p.get("id", "siliconflow"),
            "name": p.get("name", p.get("id", "")),
            "kind": kind,
            "base_url": p.get("base_url", "") or "",
            "api_key": p.get("api_key", "") or "",
            "model": p.get("model", "") or "",
            "priority": int(p.get("priority", 0) or 0),
            "enabled": bool(p.get("enabled", True)),
        })
    return [p for p in out if p["kind"] != OFFLINE_ID and p["api_key"] and p["base_url"]]


def probe(prov: dict, tenant_id=None) -> dict:
    """供应商配置验活：拿候选配置真打一次上游，用于「保存前先确认」。

    与 _post 的区别：
      - max_tokens=1，不烧 token；
      - 不走重试/故障转移（单点判定，否则 A 挂了就误报 B 的错）；
      - 把上游原始错误体回传，让用户能分清「Key 失效(401)」「模型名错(404)」
        「余额不足(402)」——这三者过去在 UI 上长得一模一样。

    返回 {ok, err, hint, detail}，绝不抛异常（探测失败是正常结果，不是错误）。
    """
    hint_map = {
        "401": "API Key 无效或已被撤销 —— 请到供应商控制台重新复制 Key",
        "402": "账户余额不足或欠费 —— 请充值后重试",
        "403": "Key 无该模型/该资源的调用权限 —— 请检查模型名或套餐范围",
        "404": "接口地址或模型名不存在 —— 请检查 Base URL（通常需带 /v1）与模型名拼写",
        "429": "触发限流 —— 稍后重试，或换 Key",
        "500": "上游服务内部错误 —— 可稍后重试",
        "502": "上游网关错误 —— 通常是供应商侧临时故障",
        "503": "上游服务不可用 —— 供应商可能维护中",
        "504": "上游响应超时 —— 可稍后重试或换更快的模型",
    }
    try:
        r = requests.post(
            f"{(prov.get('base_url') or '').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {prov.get('api_key', '')}",
                     "Content-Type": "application/json"},
            json={"model": prov.get("model", ""),
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1},
            timeout=20,
        )
    except requests.exceptions.Timeout:
        return {"ok": False, "err": "timeout", "hint": "连接超时 —— 请检查 Base URL 或网络代理",
                "detail": ""}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "err": "network", "hint": f"网络不可达：{str(exc)[:120]}", "detail": ""}

    if r.status_code == 200:
        return {"ok": True, "err": "", "hint": "连通正常，Key 有效", "detail": ""}
    body = (r.text or "")[:300]
    return {"ok": False, "err": f"HTTP {r.status_code}",
            "hint": hint_map.get(str(r.status_code), "上游返回异常"),
            "detail": body}


def _post(payload: dict, prov: dict, tenant_id=None):
    # 出境闸门：多供应商故障转移会依次打到不同 base_url，每一次都须过闸（否则
    # 「切一个供应商就绕过管控」）。被拒 → 视为该供应商失败，继续走下一个/离线兜底。
    from . import egress
    if egress.blocked("llm", prov.get("base_url", ""), payload, tenant_id=tenant_id):
        return None, "egress_denied"
    last = ""
    timeout = int(getattr(config, "LLM_TIMEOUT", 60) or 60)
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                f"{prov['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {prov['api_key']}"},
                json=payload, timeout=timeout,
            )
            resp.raise_for_status()
            return resp, None
        except requests.exceptions.Timeout:
            last = "timeout"; time.sleep(1.5 * (attempt + 1))
        except requests.exceptions.HTTPError as he:
            st = he.response.status_code if he.response is not None else 0
            last = f"HTTP {st}"
            if st in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1)); continue
            return None, last
        except requests.exceptions.RequestException as re:
            last = str(re)[:200]; time.sleep(1.5 * (attempt + 1))
    return None, last


def chat(system, prompt, history=None, provider_id=None, tenant_id=None, conn=None, llm_fn=None):
    """路由对话。provider_id 显式 > active > 首个 enabled。失败按序故障转移 → 离线兜底。

    llm_fn 仅用于测试注入（签名 (prov, payload)->(text_or_None, err)），生产走真实 HTTP。
    """
    c = conn or db.connect()
    # 1) 选定主供应商 + 故障转移顺序（与 chat_with_tools 共用同一套解析规则）
    prov, order = _order_for(provider_id, c)
    if prov is None or prov["kind"] == OFFLINE_ID or not prov.get("api_key"):
        usage.record(tenant_id, "llm", "offline", prompt_text=prompt, completion_text="")
        return {"ok": False, "text": "", "err": "offline", "model": "offline",
                "provider": OFFLINE_ID, "usage": None}

    # 2) 尝试主供应商 + 故障转移
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-10:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"][:800]})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": prov["model"], "messages": messages, "temperature": 0.1}
    for p in order:
        if not p.get("api_key"):
            continue
        if llm_fn is not None:
            text, err = llm_fn(p, payload)
        else:
            resp, err = _post(payload, p, tenant_id)
            if resp is None:
                continue
            text = resp.json()["choices"][0]["message"]["content"]
        if text is not None:
            usage.record(tenant_id, "llm", p["model"], prompt_text=prompt, completion_text=text)
            return {"ok": True, "text": text, "err": "", "model": p["model"],
                    "provider": p["id"], "usage": None}
    # 3) 全失败 → 离线兜底
    usage.record(tenant_id, "llm", "offline", prompt_text=prompt, completion_text="")
    return {"ok": False, "text": "", "err": "all_providers_failed", "model": "offline",
            "provider": OFFLINE_ID, "usage": None}


def _order_for(provider_id, c):
    """解析主供应商 + 故障转移顺序。显式 provider_id > active > 首个 enabled。

    注册表为空时回落 config.LLM_PROVIDERS（见 _fallback_providers 注释）。
    """
    prov = _provider_by_id(provider_id, c) if provider_id else None
    if prov is None:
        aid = get_active(c)
        prov = _provider_by_id(aid, c) if aid else None
    pool = _enabled_ordered(c) or _fallback_providers()
    if prov is None:
        prov = (pool or [None])[0]
    if prov is None:
        return None, []
    rest = [p for p in pool if p["id"] != prov["id"]]
    return prov, [prov] + rest


def _record_usage(tenant_id, model_name, prompt_text, completion_text, u):
    """统一记账：token + 成本（有真实 usage 时按 usage.price 精算）。"""
    pt = ct = None
    cost = None
    if u:
        pt = u.get("prompt_tokens")
        ct = u.get("completion_tokens")
        if u.get("total_tokens"):
            try:
                pin, pout = usage.price(model_name)
            except Exception:
                pin = pout = 0.0
            cost = (pt or 0) / 1000.0 * pin + (ct or 0) / 1000.0 * pout
    try:
        usage.record(tenant_id, "llm", model_name, prompt_text=prompt_text,
                     completion_text=completion_text or "",
                     prompt_tokens=pt, completion_tokens=ct, cost=cost)
    except Exception:
        pass
    return pt, ct, cost


def _parse_tool_calls(msg: dict) -> list:
    """OpenAI 兼容 tool_calls → [{name, arguments(dict), id}]。参数非法时降级为 {}。"""
    out = []
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function", {}) or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        out.append({"name": fn.get("name", ""), "arguments": args, "id": tc.get("id", "")})
    return out


def chat_with_tools(system: str, messages: list, tools: list | None = None,
                    provider_id: str | None = None, model: str | None = None,
                    tenant_id=None, conn=None, temperature: float | None = None) -> dict:
    """带 function calling 的多供应商路由（agent_loop 的 LLM 出口）。

    与 chat() 共享同一套「供应商解析 → 出境闸门 → 瞬断重试 → 顺序故障转移 → 离线兜底」，
    额外携带 tools/tool_choice 并解析 tool_calls。

    返回结构与 gateway.chat_with_tools 保持兼容：
      {ok, text, tool_calls, err, model, provider, usage, cost, attempts}
    attempts 记录每个供应商的失败原因，供 emit 上报与排障（OpenClaw §4.3 failover 语义）。
    """
    c = conn or db.connect()
    prov, order = _order_for(provider_id, c)
    if prov is None or prov.get("kind") == OFFLINE_ID or not prov.get("api_key"):
        usage.record(tenant_id, "llm", "offline", prompt_text=str(messages), completion_text="")
        return {"ok": False, "text": "", "tool_calls": [], "err": "offline",
                "model": "offline", "provider": OFFLINE_ID, "usage": None,
                "cost": None, "attempts": []}

    full_msgs = [{"role": "system", "content": system}] + list(messages or [])
    base_payload = {
        "messages": full_msgs,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "tools": tools or [],
        "tool_choice": "auto",
    }
    attempts = []
    for p in order:
        if not p.get("api_key") or p.get("kind") == OFFLINE_ID:
            continue
        # model 覆盖只对显式指定生效；否则用各供应商自己的默认模型（故障转移后
        # 不能继续用主供应商的模型名 —— 部分 OpenAI 兼容网关会直接 400）。
        eff_model = model if (model and p["id"] == prov["id"]) else p["model"]
        payload = dict(base_payload, model=eff_model)
        resp, err = _post(payload, p, tenant_id)
        if resp is None:
            attempts.append({"provider": p["id"], "model": eff_model, "ok": False, "err": err})
            continue
        try:
            js = resp.json()
            msg = js["choices"][0]["message"]
        except Exception as exc:
            attempts.append({"provider": p["id"], "model": eff_model,
                             "ok": False, "err": "bad_response: %s" % str(exc)[:120]})
            continue
        text = msg.get("content") or ""
        u = js.get("usage")
        _, _, cost = _record_usage(tenant_id, eff_model, str(messages), text, u)
        u = dict(u) if isinstance(u, dict) else {}
        u["cost"] = cost
        attempts.append({"provider": p["id"], "model": eff_model, "ok": True, "err": ""})
        return {"ok": True, "text": text, "tool_calls": _parse_tool_calls(msg),
                "err": "", "model": eff_model, "provider": p["id"],
                "usage": u, "cost": cost, "attempts": attempts}

    usage.record(tenant_id, "llm", "offline", prompt_text=str(messages), completion_text="")
    return {"ok": False, "text": "", "tool_calls": [], "err": "all_providers_failed",
            "model": "offline", "provider": OFFLINE_ID, "usage": None,
            "cost": None, "attempts": attempts}

