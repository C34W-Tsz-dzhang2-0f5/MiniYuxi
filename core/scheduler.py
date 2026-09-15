"""定时 Loop（自动化循环 · Loop 工程六零件之 Automations）：基于 spec 的定时任务调度。

设计：schedules 表运行时建（不碰冻结 db.py）。spec 支持三种：
  - {"kind":"interval","seconds":N}          每 N 秒
  - {"kind":"every_minutes","minutes":N}     每 N 分钟
  - {"kind":"daily","at":"09:00"}            每天该时刻
due_jobs / mark_run 均支持注入 now，便于测试与可重放。
零新增依赖（仅标准库 datetime/json）。
"""
import json
import uuid
from datetime import datetime, timedelta
from . import db

_KINDS = {"interval", "every_minutes", "daily"}


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS schedules(
                id TEXT PRIMARY KEY,
                name TEXT,
                spec TEXT,
                payload TEXT,
                tenant_id TEXT DEFAULT 'default',
                last_run TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def register(name, spec, payload, tenant_id="default", conn=None) -> str:
    if spec.get("kind") not in _KINDS:
        raise ValueError("spec.kind 必须是 interval / every_minutes / daily")
    c = _conn(conn)
    init(c)
    jid = "job_" + uuid.uuid4().hex[:12]
    c.execute(
        "INSERT INTO schedules(id,name,spec,payload,tenant_id) VALUES(?,?,?,?,?)",
        (jid, name, json.dumps(spec, ensure_ascii=False),
         json.dumps(payload, ensure_ascii=False), tenant_id),
    )
    c.commit()
    return jid


def _due(spec, last_dt, now):
    kind = spec.get("kind")
    if kind == "interval":
        secs = spec.get("seconds", 3600)
        if last_dt is None:
            return True
        return (now - last_dt).total_seconds() >= secs
    if kind == "every_minutes":
        mins = spec.get("minutes", 60)
        if last_dt is None:
            return True
        return (now - last_dt).total_seconds() >= mins * 60
    if kind == "daily":
        at = spec.get("at", "09:00")
        hh, mm = int(at[:2]), int(at[3:5])
        if last_dt is None:
            return True
        today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return now >= today and last_dt < today
    return False


def due_jobs(now=None, conn=None) -> list:
    c = _conn(conn)
    init(c)
    now = now or datetime.now()
    rows = c.execute("SELECT * FROM schedules WHERE status='active'").fetchall()
    out = []
    for r in rows:
        spec = json.loads(r["spec"])
        last_dt = _parse_dt(r["last_run"])
        if _due(spec, last_dt, now):
            d = dict(r)
            d["spec"] = spec
            d["payload"] = json.loads(r["payload"])
            out.append(d)
    return out


def mark_run(job_id, status="ok", now=None, conn=None):
    """记录一次执行；status='pause' 时把任务置为 paused（停止后续触发）。"""
    c = _conn(conn)
    init(c)
    now = now or datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    if status == "pause":
        c.execute("UPDATE schedules SET last_run=?, status='paused' WHERE id=?", (ts, job_id))
    else:
        c.execute("UPDATE schedules SET last_run=? WHERE id=?", (ts, job_id))
    c.commit()
