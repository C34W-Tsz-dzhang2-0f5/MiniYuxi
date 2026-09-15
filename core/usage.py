"""Token 成本监控（T3）：运行时建 usage_log 表，记录每次 LLM / Embedding 调用的 token 消耗与成本。

设计：零新增依赖，复用 db.connect()；CREATE TABLE IF NOT EXISTS 绕开冻结的 db.py。
所有写入均被上层 try/except 守护，绝不因统计失败影响主链路（包括 selftest 离线链路）。
"""
import re
from . import config, db

# 每千 token 价格（人民币，估算；SiliconFlow 按实际用量计费，这里给保守默认值）
_PRICE = {
    "Qwen/Qwen2.5-72B-Instruct": (0.004, 0.012),
    "Qwen/Qwen2.5-7B-Instruct": (0.0007, 0.0007),
    "default": (0.004, 0.012),
}


def price(model: str):
    for k, v in _PRICE.items():
        if k in (model or ""):
            return v
    return _PRICE["default"]


def init() -> None:
    try:
        conn = db.connect()
        conn.execute(
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
        conn.commit()
    except Exception:
        pass


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    others = len(re.findall(r"[a-zA-Z0-9]+", text))
    return cjk + others


def record(tenant_id, kind, model, prompt_text="", completion_text="",
           prompt_tokens=None, completion_tokens=None, cost=None) -> None:
    """记录一次调用。上游返回精确 token 数则用之，否则按文本估算。"""
    try:
        init()
        if prompt_tokens is None:
            prompt_tokens = _estimate_tokens(prompt_text)
        if completion_tokens is None:
            completion_tokens = _estimate_tokens(completion_text)
        pin, pout = price(model)
        if cost is None:
            cost = (prompt_tokens / 1000.0) * pin + (completion_tokens / 1000.0) * pout
        conn = db.connect()
        conn.execute(
            "INSERT INTO usage_log(tenant_id,kind,model,prompt_tokens,completion_tokens,cost) VALUES(?,?,?,?,?,?)",
            (tenant_id, kind, model or "offline", int(prompt_tokens), int(completion_tokens), round(float(cost), 6)),
        )
        conn.commit()
    except Exception:
        pass


def stats(tenant_id=None) -> dict:
    try:
        init()
        conn = db.connect()
        where = "WHERE tenant_id=?" if tenant_id else ""
        params = (tenant_id,) if tenant_id else ()
        total = conn.execute(
            f"SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), COALESCE(SUM(cost),0), COUNT(*) FROM usage_log {where}",
            params,
        ).fetchone()
        by_model = conn.execute(
            f"SELECT model, COALESCE(SUM(prompt_tokens),0) pt, COALESCE(SUM(completion_tokens),0) ct, COALESCE(SUM(cost),0) c, COUNT(*) n FROM usage_log {where} GROUP BY model ORDER BY c DESC",
            params,
        ).fetchall()
        recent = conn.execute(
            f"SELECT kind, model, prompt_tokens, completion_tokens, cost, created_at FROM usage_log {where} ORDER BY id DESC LIMIT 20",
            params,
        ).fetchall()
        return {
            "total": {"prompt_tokens": total[0], "completion_tokens": total[1], "cost": round(total[2], 4), "calls": total[3]},
            "by_model": [dict(zip(["model", "prompt_tokens", "completion_tokens", "cost", "calls"], r)) for r in by_model],
            "recent": [dict(zip(["kind", "model", "prompt_tokens", "completion_tokens", "cost", "created_at"], r)) for r in recent],
        }
    except Exception as exc:
        return {"error": str(exc), "total": {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0, "calls": 0}}
