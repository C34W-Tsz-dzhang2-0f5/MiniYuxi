"""M6 流程画布持久化（域13 后端）：供可视化画布存取的 flow 定义存储。

设计：复用 db.connect()（与 memory.py 同模式），自建 flows 表，零修改 db.py。
红线：不碰 core/agent.py / core/rag.py / core/db.py；本文件为新增。
供 web/flow-canvas.*（Dify 风格画布前端）存取；与现有 /api/agent/flows（代码定义流程）互补：
前者是"代码/HITL 执行流"，本模块是"用户可视化编排流"的存储底座。
"""
import json
import uuid

from . import db


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS flows(
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                name TEXT,
                definition TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def save_flow(flow_id, tenant_id, name, definition, conn=None) -> str:
    """upsert 一个 flow 定义（definition 可为 dict/list 或已序列化字符串）。返回 flow id。"""
    init()
    c = _conn(conn)
    fid = (flow_id or "").strip() or ("flow_" + uuid.uuid4().hex[:12])
    payload = definition if isinstance(definition, str) else json.dumps(definition, ensure_ascii=False)
    try:
        c.execute(
            """INSERT INTO flows(id, tenant_id, name, definition, updated_at)
               VALUES(?,?,?,?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, definition=excluded.definition, updated_at=datetime('now')""",
            (fid, tenant_id, name or fid, payload),
        )
        c.commit()
    except Exception:
        pass
    return fid


def list_flows(tenant_id, conn=None) -> list:
    init()
    c = _conn(conn)
    try:
        rows = c.execute(
            "SELECT id, name, updated_at FROM flows WHERE tenant_id=? ORDER BY updated_at DESC",
            (tenant_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "updated_at": r["updated_at"]} for r in rows]
    except Exception:
        return []


def get_flow(flow_id, tenant_id=None, conn=None):
    init()
    c = _conn(conn)
    try:
        if tenant_id:
            r = c.execute(
                "SELECT * FROM flows WHERE id=? AND tenant_id=?", (flow_id, tenant_id)
            ).fetchone()
        else:
            r = c.execute("SELECT * FROM flows WHERE id=?", (flow_id,)).fetchone()
    except Exception:
        r = None
    if not r:
        return None
    try:
        definition = json.loads(r["definition"])
    except Exception:
        definition = {"raw": r["definition"]}
    return {
        "id": r["id"], "name": r["name"], "definition": definition,
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def delete_flow(flow_id, tenant_id=None, conn=None) -> int:
    init()
    c = _conn(conn)
    try:
        if tenant_id:
            cur = c.execute("DELETE FROM flows WHERE id=? AND tenant_id=?", (flow_id, tenant_id))
        else:
            cur = c.execute("DELETE FROM flows WHERE id=?", (flow_id,))
        c.commit()
        return cur.rowcount
    except Exception:
        return 0
