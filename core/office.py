"""办公操作面（Office Surface）· Univer 文档持久化。

职责：为 MiniYuxi 内置办公套件（Univer 表格 / 文档）提供纯本地的存档能力。

设计要点：
  1. 数据不出机：办公文档快照（Univer 的 IWorkbookData / IDocumentData JSON）
     全部落在本地 SQLite（config.DB_PATH），不经过任何外部服务；
  2. 与 core 其它模块同构：连接用 db.connect()（线程本地，不可 close），
     每个公开函数带 conn=None，表含 tenant_id，写入走参数化 SQL；
  3. 零新增依赖：仅 stdlib + json + uuid。

表结构：
  office_docs(doc_id, tenant_id, kind, name, data, created_at, updated_at)
    kind: 'sheet'（表格） | 'doc'（文档）
    data: Univer 快照 JSON 字符串（fWorkbook.save() / fDocument.save() 的返回值）
"""
import json
import uuid

from core import config, db

_TABLE = "office_docs"


def _conn(conn=None):
    """连接解析：优先复用传入连接，否则取线程本地连接。"""
    return conn if conn is not None else db.connect()


def _new_id() -> str:
    return "of" + uuid.uuid4().hex[:12]


def init(conn=None) -> None:
    """运行时建表（幂等）。失败不阻塞主链路，由调用方 try/except 兜住。"""
    c = _conn(conn)
    c.execute(
        """CREATE TABLE IF NOT EXISTS office_docs(
            doc_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'sheet',
            name TEXT NOT NULL DEFAULT '未命名',
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_office_docs_tenant ON office_docs(tenant_id, updated_at DESC)"
    )
    c.commit()


def list_docs(tenant_id: str, kind: str = "", conn=None) -> list:
    """列出本租户办公文档元数据（不含 data，避免列表接口传输大 JSON）。"""
    c = _conn(conn)
    if kind:
        rows = c.execute(
            "SELECT doc_id,kind,name,created_at,updated_at FROM %s "
            "WHERE tenant_id=? AND kind=? ORDER BY updated_at DESC" % _TABLE,
            (tenant_id, kind),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT doc_id,kind,name,created_at,updated_at FROM %s "
            "WHERE tenant_id=? ORDER BY updated_at DESC" % _TABLE,
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_doc(tenant_id: str, doc_id: str, conn=None):
    """取单个文档（含 data）。不存在返回 None。"""
    c = _conn(conn)
    row = c.execute(
        "SELECT doc_id,kind,name,data,created_at,updated_at FROM %s "
        "WHERE tenant_id=? AND doc_id=?" % _TABLE,
        (tenant_id, doc_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    # data 以 TEXT 存的 JSON，反序列化回 dict；损坏时降级为空 dict 而非抛错
    try:
        d["data"] = json.loads(d["data"] or "{}")
    except (ValueError, TypeError):
        d["data"] = {}
    return d


def save_doc(tenant_id: str, data: dict, kind: str = "sheet",
             name: str = "未命名", doc_id: str = "", conn=None) -> str:
    """保存（新建或更新）办公文档，返回 doc_id。

    data 为 Univer 快照 dict；doc_id 为空则自动生成（新建）。
    """
    c = _conn(conn)
    payload = json.dumps(data or {}, ensure_ascii=False)
    if doc_id:
        cur = c.execute(
            "UPDATE %s SET kind=?,name=?,data=?,updated_at=datetime('now') "
            "WHERE tenant_id=? AND doc_id=?" % _TABLE,
            (kind, name, payload, tenant_id, doc_id),
        )
        if cur.rowcount == 0:
            # 传入的 doc_id 不存在（如前端本地新建后换端打开）→ 转为插入
            c.execute(
                "INSERT INTO %s(doc_id,tenant_id,kind,name,data) VALUES(?,?,?,?,?)" % _TABLE,
                (doc_id, tenant_id, kind, name, payload),
            )
    else:
        doc_id = _new_id()
        c.execute(
            "INSERT INTO %s(doc_id,tenant_id,kind,name,data) VALUES(?,?,?,?,?)" % _TABLE,
            (doc_id, tenant_id, kind, name, payload),
        )
    c.commit()
    return doc_id


def delete_doc(tenant_id: str, doc_id: str, conn=None) -> bool:
    """删除文档，返回是否命中。"""
    c = _conn(conn)
    cur = c.execute(
        "DELETE FROM %s WHERE tenant_id=? AND doc_id=?" % _TABLE, (tenant_id, doc_id)
    )
    c.commit()
    return cur.rowcount > 0
