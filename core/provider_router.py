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
from . import db, usage

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


def _post(payload: dict, prov: dict):
    last = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                f"{prov['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {prov['api_key']}"},
                json=payload, timeout=60,
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
    # 1) 选定主供应商
    prov = _provider_by_id(provider_id, c) if provider_id else None
    if prov is None:
        aid = get_active(c)
        prov = _provider_by_id(aid, c) if aid else None
    if prov is None:
        prov = (_enabled_ordered(c) or [None])[0]
    if prov is None or prov["kind"] == OFFLINE_ID or not prov.get("api_key"):
        usage.record(tenant_id, "llm", "offline", prompt_text=prompt, completion_text="")
        return {"ok": False, "text": "", "err": "offline", "model": "offline",
                "provider": OFFLINE_ID, "usage": None}

    # 2) 尝试主供应商 + 故障转移
    order = [prov] + [p for p in _enabled_ordered(c) if p["id"] != prov["id"]]
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
            resp, err = _post(payload, p)
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
