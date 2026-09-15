"""模块三 · 招聘数据看板：周度漏斗汇总 + offer—到岗断档预警。

设计：零新增依赖；运行时建表。漏斗各阶段计数独立记录，按 (租户,周) 聚合；
断档预警以「到岗数 / offer数」比值低于阈值触发，阈值可配。
"""
from . import db

STAGES = ["简历", "初筛", "面试", "offer", "到岗"]
# offer→到岗 健康比例下限（低于即预警）
GAP_THRESHOLD = 0.6


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS recruit_funnel(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                week TEXT,
                stage TEXT,
                cnt INTEGER DEFAULT 0,
                UNIQUE(tenant_id, week, stage)
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def record(tenant_id, week, stage, cnt, conn=None):
    if stage not in STAGES:
        raise ValueError(f"未知阶段 {stage}，应为 {STAGES}")
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT OR REPLACE INTO recruit_funnel(tenant_id,week,stage,cnt) VALUES(?,?,?,?)",
        (tenant_id, week, stage, int(cnt)),
    )
    c.commit()
    return True


def weekly(tenant_id, week, conn=None) -> dict:
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT stage,cnt FROM recruit_funnel WHERE tenant_id=? AND week=?", (tenant_id, week)
    ).fetchall()
    d = {s: 0 for s in STAGES}
    for r in rows:
        d[r["stage"]] = r["cnt"]
    return d


def detect_gap(tenant_id, week=None, threshold=GAP_THRESHOLD, conn=None) -> dict:
    """对单周或全量最新周做 offer→到岗 断档检测。"""
    c = _conn(conn)
    init(c)
    if week:
        weeks = [week]
    else:
        weeks = [r["week"] for r in c.execute(
            "SELECT DISTINCT week FROM recruit_funnel WHERE tenant_id=? ORDER BY week DESC LIMIT 4", (tenant_id,)
        ).fetchall()]
    alerts = []
    for w in weeks:
        d = weekly(tenant_id, w, c)
        off, onb = d.get("offer", 0), d.get("到岗", 0)
        ratio = (onb / off) if off else (1.0 if onb == 0 else 0.0)
        if off and ratio < threshold:
            alerts.append({
                "week": w, "offer": off, "到岗": onb, "ratio": round(ratio, 2),
                "risk": "🔴 高" if ratio < 0.4 else "🟡 中",
                "msg": f"第 {w} 周发 offer {off} 人，实际到岗 {onb} 人，到岗率 {round(ratio*100)}%，存在断档。",
            })
    return {"weeks_checked": weeks, "alerts": alerts, "threshold": threshold}


def summary(tenant_id, conn=None) -> dict:
    c = _conn(conn)
    init(c)
    weeks = [r["week"] for r in c.execute(
        "SELECT DISTINCT week FROM recruit_funnel WHERE tenant_id=? ORDER BY week DESC LIMIT 8", (tenant_id,)
    ).fetchall()]
    series = [{"week": w, **weekly(tenant_id, w, c)} for w in weeks]
    gap = detect_gap(tenant_id, conn=c)
    return {"stages": STAGES, "series": series, "gap_alerts": gap["alerts"]}
