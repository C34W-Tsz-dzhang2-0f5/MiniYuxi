"""P1 工作台（可观测性聚合）：汇总 usage_log / audit_logs / kb 文档为工作台数据。

设计：零新增依赖；新表 usage_daily 走运行时 CREATE TABLE IF NOT EXISTS，不碰冻结 db.py。
所有写入均被上层 try/except 守护，绝不因统计失败影响主链路（含 selftest 离线链路）。
"""
from . import db


def init(conn=None):
    c = conn or db.connect()
    try:
        # 聚合依赖 usage_log（属 usage.py）；为保证聚合自给自足，此处幂等补建（与 usage.init 不冲突）
        c.execute(
            """CREATE TABLE IF NOT EXISTS usage_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                kind TEXT,
                model TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS usage_daily(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                day TEXT,
                calls INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(tenant_id, day)
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def rollup_daily(conn=None):
    """把 usage_log 按 (租户,天) 聚合成 usage_daily 物化视图，便于工作台画趋势线。"""
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT tenant_id, date(created_at) AS day, COUNT(*) calls, "
        "COALESCE(SUM(prompt_tokens),0) pt, COALESCE(SUM(completion_tokens),0) ct, "
        "COALESCE(SUM(cost),0) cost FROM usage_log GROUP BY tenant_id, day"
    ).fetchall()
    n = 0
    for r in rows:
        c.execute(
            "INSERT OR REPLACE INTO usage_daily(tenant_id,day,calls,prompt_tokens,completion_tokens,cost) "
            "VALUES(?,?,?,?,?,?)",
            (r["tenant_id"], r["day"], r["calls"], r["pt"] or 0, r["ct"] or 0, r["cost"] or 0),
        )
        n += 1
    c.commit()
    return n


def aggregate(tenant_id, conn=None) -> dict:
    """工作台核心聚合：调用量/Token/成本/按模型拆分/每日趋势。"""
    c = _conn(conn)
    init(c)
    total = c.execute(
        "SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
        "COALESCE(SUM(cost),0), COUNT(*) FROM usage_log WHERE tenant_id=?",
        (tenant_id,),
    ).fetchone()
    by_model = c.execute(
        "SELECT model, COALESCE(SUM(prompt_tokens),0) pt, COALESCE(SUM(completion_tokens),0) ct, "
        "COALESCE(SUM(cost),0) c, COUNT(*) n FROM usage_log WHERE tenant_id=? "
        "GROUP BY model ORDER BY c DESC",
        (tenant_id,),
    ).fetchall()
    daily = c.execute(
        "SELECT day, calls, cost FROM usage_daily WHERE tenant_id=? ORDER BY day DESC LIMIT 14",
        (tenant_id,),
    ).fetchall()
    return {
        "total": {
            "prompt_tokens": total[0],
            "completion_tokens": total[1],
            "cost": round(total[2] or 0, 4),
            "calls": total[3],
        },
        "by_model": [
            dict(zip(["model", "prompt_tokens", "completion_tokens", "cost", "calls"], r))
            for r in by_model
        ],
        "daily": [dict(zip(["day", "calls", "cost"], r)) for r in daily],
    }
