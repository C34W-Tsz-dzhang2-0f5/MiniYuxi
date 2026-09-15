"""服务端记忆（T3）：跨浏览器/会话的长期记忆。

之前多轮上下文只存在浏览器 localStorage，换浏览器/清缓存即失。本模块把"对话摘要"
持久化到服务端 memories 表，使 Agent 具备真正的长期记忆（对标 WorkBuddy/Hermes）。
不自动改 prompt、不新增依赖；CREATE TABLE IF NOT EXISTS 绕开冻结 db.py，写入失败静默不影响主链路。
"""
from . import db


def init():
    try:
        c = db.connect()
        c.execute(
            """CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                session_id TEXT DEFAULT '',
                role TEXT,
                content TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def append(tenant_id, role, content, session_id="", limit=80):
    """写入一条记忆；超出 limit 条时删除最旧，防止无限膨胀。"""
    if not content or not content.strip():
        return
    try:
        init()
        c = db.connect()
        c.execute(
            "INSERT INTO memories(tenant_id,session_id,role,content) VALUES(?,?,?,?)",
            (tenant_id, session_id, role, content[:1000]),
        )
        c.execute(
            "DELETE FROM memories WHERE tenant_id=? AND id NOT IN "
            "(SELECT id FROM memories WHERE tenant_id=? ORDER BY id DESC LIMIT ?)",
            (tenant_id, tenant_id, limit),
        )
        c.commit()
    except Exception:
        pass


def recall(tenant_id, limit=8) -> list:
    """取该租户最近的记忆摘要（用于注入 system）。"""
    try:
        init()
        c = db.connect()
        rows = c.execute(
            "SELECT content FROM memories WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
        return [r["content"] for r in rows][::-1]  # 时间正序
    except Exception:
        return []
