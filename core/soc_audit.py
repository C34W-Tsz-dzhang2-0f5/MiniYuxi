"""SOC 级结构化审计日志（深度构造·项3 技术控制层）。

把轻量 usage_log 升级为：
- 结构化事件（actor/role/action/target/result/severity/src_ip/session_id/request_id/detail_json）；
- 哈希链（hash chaining）：每行 hash = sha256(prev_hash + 规范事件)，形成防篡改证据链；
- 可验证（verify_chain）：重算并比对，任何行被篡改即定位 broken_at；
- 可查询 / 可导出（SOC 报告）。

说明：这是"技术控制层"。等保/ISO 还要求组织制度、边界防护、运维流程等，
证书由测评机构/认证 body 出具；本模块让技术侧审计留痕达到可举证、可审计、防篡改。
"""
import hashlib
import json
from . import db

SEVERITY = ("info", "warn", "error", "critical")
GENESIS = "GENESIS"


def init(conn=None):
    c = conn or db.connect()
    c.execute("""CREATE TABLE IF NOT EXISTS audit_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, seq INTEGER NOT NULL,
        tenant_id TEXT, actor TEXT, role TEXT, action TEXT, target TEXT,
        result TEXT NOT NULL DEFAULT 'success', severity TEXT NOT NULL DEFAULT 'info',
        src_ip TEXT, session_id TEXT, request_id TEXT, detail_json TEXT,
        prev_hash TEXT NOT NULL, hash TEXT NOT NULL, ts TEXT DEFAULT (datetime('now')))""")
    c.commit()


def _canonical(e, prev_hash):
    base = "||".join([
        str(e.get("tenant_id") or ""), str(e.get("actor") or ""), str(e.get("role") or ""),
        str(e.get("action") or ""), str(e.get("target") or ""), str(e.get("result") or ""),
        str(e.get("severity") or "info"), str(e.get("src_ip") or ""),
        str(e.get("session_id") or ""), str(e.get("request_id") or ""),
        json.dumps(e.get("detail") or {}, sort_keys=True, ensure_ascii=False),
        prev_hash,
    ])
    return base


def log(event: dict, conn=None):
    c = conn or db.connect()
    last = c.execute("SELECT hash, seq FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = last["hash"] if last else GENESIS
    seq = (last["seq"] + 1) if last else 1
    sev = event.get("severity", "info")
    if sev not in SEVERITY:
        sev = "info"
    canon = _canonical(event, prev_hash)
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    c.execute(
        """INSERT INTO audit_events(seq,tenant_id,actor,role,action,target,result,severity,
           src_ip,session_id,request_id,detail_json,prev_hash,hash)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (seq, event.get("tenant_id"), event.get("actor"), event.get("role"),
         event.get("action"), event.get("target"), event.get("result", "success"), sev,
         event.get("src_ip"), event.get("session_id"), event.get("request_id"),
         json.dumps(event.get("detail") or {}, ensure_ascii=False), prev_hash, h),
    )
    c.commit()
    return {"seq": seq, "hash": h}


def verify_chain(conn=None):
    """重算哈希链，返回 {ok, broken_at, count}。任何行被改都定位。"""
    c = conn or db.connect()
    rows = c.execute("SELECT seq,tenant_id,actor,role,action,target,result,severity,src_ip,"
                     "session_id,request_id,detail_json,prev_hash,hash FROM audit_events "
                     "ORDER BY id").fetchall()
    prev = GENESIS
    for r in rows:
        detail = json.loads(r["detail_json"] or "{}")
        canon = _canonical({
            "tenant_id": r["tenant_id"], "actor": r["actor"], "role": r["role"],
            "action": r["action"], "target": r["target"], "result": r["result"],
            "severity": r["severity"], "src_ip": r["src_ip"], "session_id": r["session_id"],
            "request_id": r["request_id"], "detail": detail,
        }, prev)
        if hashlib.sha256(canon.encode("utf-8")).hexdigest() != r["hash"]:
            return {"ok": False, "broken_at": r["seq"], "count": len(rows)}
        prev = r["hash"]
    return {"ok": True, "broken_at": None, "count": len(rows)}


def query(filters=None, limit=200, conn=None):
    c = conn or db.connect()
    filters = filters or {}
    sql = "SELECT * FROM audit_events WHERE 1=1"
    args = []
    for col in ("tenant_id", "actor", "action", "result", "severity"):
        if filters.get(col):
            sql += f" AND {col}=?"; args.append(filters[col])
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def stats(conn=None):
    c = conn or db.connect()
    total = c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    by_sev = {}
    for r in c.execute("SELECT severity,COUNT(*) n FROM audit_events GROUP BY severity"):
        by_sev[r["severity"]] = r["n"]
    by_res = {}
    for r in c.execute("SELECT result,COUNT(*) n FROM audit_events GROUP BY result"):
        by_res[r["result"]] = r["n"]
    return {"total": total, "by_severity": by_sev, "by_result": by_res}


def export(conn=None):
    """导出 SOC 报告形态（事件列表 + 链完整性结论）。"""
    c = conn or db.connect()
    rows = c.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    return {"events": [dict(r) for r in rows], "chain": verify_chain(c)}
