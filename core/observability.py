"""可观测性（企业级要素④）：贯穿 agent 运行的 trace_id + 结构化 span 落库 + 指标导出。

设计（对齐 CONTEXT.md 术语）：
- 单一入口 start_trace() 产生 trace_id，贯穿 retrieval → tool → action 全链路。
- span() 上下文管理器记录 开始/结束/耗时/令牌/成本，落库 traces 表。
- get_metrics() 导出成功率 / 延迟 / 单次成本 / 升级率（供监控面板接入）。
- 零新增依赖，复用 db.connect()；所有写入 try/except 守护，绝不因统计失败影响主链路。
"""
import json
import time
import uuid
import contextvars
from . import db

TRACE_ID = contextvars.ContextVar("miniyuxi_trace_id", default=None)


def start_trace(trace_id=None):
    tid = trace_id or uuid.uuid4().hex
    TRACE_ID.set(tid)
    return tid


def current_trace_id():
    return TRACE_ID.get()


def attach_trace_id(trace_id):
    if trace_id:
        TRACE_ID.set(trace_id)


def _json_safe(meta):
    if not meta:
        return None
    try:
        return json.dumps(meta, ensure_ascii=False)
    except Exception:
        return None


def _persist(conn, trace_id, name, kind, tenant_id, dur_ms, tokens, cost, status, meta):
    c = conn if conn is not None else db.connect()
    c.execute(
        """CREATE TABLE IF NOT EXISTS traces(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT,
            span_name TEXT,
            kind TEXT,
            tenant_id TEXT,
            duration_ms INTEGER DEFAULT 0,
            tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0,
            status TEXT DEFAULT 'ok',
            meta TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    c.execute(
        "INSERT INTO traces(trace_id,span_name,kind,tenant_id,duration_ms,tokens,cost,status,meta) VALUES(?,?,?,?,?,?,?,?,?)",
        (trace_id, name, kind, tenant_id, int(dur_ms or 0), int(tokens or 0), round(float(cost or 0), 6),
         status or "ok", _json_safe(meta)),
    )
    c.commit()


class Span:
    """一次操作的观测单元。进入时记时，退出时落库（异常也落，并标 status=error）。"""

    def __init__(self, name, kind="span", tenant_id=None, conn=None, trace_id=None, meta=None):
        self.name = name
        self.kind = kind
        self.tenant_id = tenant_id
        self.trace_id = trace_id or current_trace_id()
        self.meta = meta or {}
        self.tokens = 0
        self.cost = 0.0
        self.status = "ok"
        self._conn = conn
        self._start = None

    def set_tokens(self, n):
        self.tokens = int(n or 0)

    def set_cost(self, c):
        self.cost = float(c or 0)

    def set_status(self, s):
        self.status = s

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            dur_ms = int((time.monotonic() - self._start) * 1000) if self._start else 0
            if exc_type is not None:
                self.status = "error"
            _persist(self._conn, self.trace_id, self.name, self.kind, self.tenant_id,
                     dur_ms, self.tokens, self.cost, self.status, self.meta)
        except Exception:
            pass
        return False  # 不吞异常


def span(name, **kw):
    return Span(name, **kw)


def get_metrics(conn=None, tenant_id=None):
    """导出观测指标：成功率 / 平均延迟 / 累计成本 / 按 span 聚合。"""
    c = conn if conn is not None else db.connect()
    where = "WHERE tenant_id=?" if tenant_id else ""
    params = (tenant_id,) if tenant_id else ()
    rows = c.execute(
        f"SELECT span_name, status, duration_ms, cost FROM traces {where}", params
    ).fetchall()
    total = len(rows)
    errors = sum(1 for r in rows if r[1] == "error")
    by_span = {}
    sum_latency = 0
    sum_cost = 0.0
    for r in rows:
        name, status, dur, cost = r
        d = by_span.setdefault(name, {"count": 0, "errors": 0, "dur_ms": 0, "cost": 0.0})
        d["count"] += 1
        if status == "error":
            d["errors"] += 1
        d["dur_ms"] += (dur or 0)
        d["cost"] += (cost or 0)
        sum_latency += (dur or 0)
        sum_cost += (cost or 0)
    return {
        "total_spans": total,
        "success_rate": (round((total - errors) / total, 4) if total else None),
        "avg_latency_ms": (round(sum_latency / total, 2) if total else None),
        "total_cost": round(sum_cost, 6),
        "by_span": by_span,
    }
