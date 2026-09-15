"""MCP 工具层 · 原生系统适配器（深度构造·项2）。

为微信 / 企业微信 / CRM / ERP / 飞书等外部系统提供统一适配器框架：
- 注册表（connectors 表）：每个外部系统一个 connector，持久化配置；
- 健康探测（health）：无凭证时返回 degraded/not_configured，绝不抛栈；
- 发送抽象（send_message）：统一信封，未配置返回 not_configured，绝不崩链路；
- 集成缝（send 实现）：若 config 含 endpoint+token，走 best-effort POST；
  真实厂商 API 调用需外部凭证，本模块只把"缝"留好，不内置任何厂商密钥。

说明：本模块交付的是"原生适配层 + 接口契约 + 优雅降级"，而非对每家厂商的
完整 API 封装（那需要各自凭证与网络）。WeCom 在本机已通过 WorkBuddy 连接器连通，
可在 config.endpoint 指向该桥，做到真正发消息。
"""
import json
import time
import requests
from . import db

KINDS = ("wecom", "wechat", "crm", "erp", "feishu")


def init(conn=None):
    c = conn or db.connect()
    c.execute("""CREATE TABLE IF NOT EXISTS connectors(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, config_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'unknown', last_check TEXT,
        created_at TEXT DEFAULT (datetime('now')))""")
    c.commit()


def register(name, kind, config=None, conn=None):
    if kind not in KINDS:
        raise ValueError(f"unsupported connector kind: {kind}; allowed={KINDS}")
    cid = f"{kind}:{name}"
    c = conn or db.connect()
    c.execute(
        "INSERT OR REPLACE INTO connectors(id,name,kind,enabled,config_json,status) VALUES(?,?,?,?,?,?)",
        (cid, name, kind, 1, json.dumps(config or {}), "unknown"),
    )
    c.commit()
    return cid


def list_connectors(conn=None):
    c = conn or db.connect()
    rows = c.execute("SELECT * FROM connectors ORDER BY kind, id").fetchall()
    return [dict(r) for r in rows]


def set_enabled(cid, enabled, conn=None):
    c = conn or db.connect()
    c.execute("UPDATE connectors SET enabled=? WHERE id=?", (1 if enabled else 0, cid))
    c.commit()


def _config(cid, conn):
    c = conn or db.connect()
    row = c.execute("SELECT * FROM connectors WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def health(conn=None):
    """批量重算各 connector 状态：有 endpoint+token=ready，仅有 endpoint=partial，否则 not_configured。"""
    c = conn or db.connect()
    out = []
    for r in c.execute("SELECT * FROM connectors").fetchall():
        d = dict(r)
        cfg = json.loads(d["config_json"] or "{}")
        if cfg.get("endpoint") and cfg.get("token"):
            status = "ready"
        elif cfg.get("endpoint"):
            status = "partial"
        else:
            status = "not_configured"
        if not d["enabled"]:
            status = "disabled"
        c.execute("UPDATE connectors SET status=?, last_check=datetime('now') WHERE id=?",
                  (status, d["id"]))
        out.append({"id": d["id"], "kind": d["kind"], "status": status})
    c.commit()
    return out


def send_message(cid, target, text, conn=None):
    """统一发送信封。未配置 → not_configured（不崩）；有 endpoint+token → best-effort POST。"""
    d = _config(cid, conn)
    if not d:
        return {"ok": False, "status": "unknown_connector", "cid": cid}
    cfg = json.loads(d["config_json"] or "{}")
    if not d["enabled"]:
        return {"ok": False, "status": "disabled", "cid": cid}
    if not (cfg.get("endpoint") and cfg.get("token")):
        return {"ok": False, "status": "not_configured", "cid": cid,
                "hint": "在 config.endpoint / config.token 填入厂商凭证后可真正发送"}
    try:
        resp = requests.post(cfg["endpoint"], headers={"Authorization": f"Bearer {cfg['token']}"},
                             json={"target": target, "text": text}, timeout=10)
        ok = resp.status_code < 400
        return {"ok": ok, "status": "sent" if ok else "error", "cid": cid,
                "http": resp.status_code}
    except Exception as e:
        return {"ok": False, "status": "transport_error", "cid": cid, "err": str(e)[:200]}
