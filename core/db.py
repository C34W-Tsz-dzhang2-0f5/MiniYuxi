"""数据层：SQLite 单文件 + sqlite-vec 向量扩展 + FTS5 全文检索。

全部为进程内嵌入库，零外部服务——这是本机（无 Docker / 无 VT-x）能跑起来的关键。

表结构：
  tenants      租户
  users        用户（含角色，租户隔离）
  docs         知识库文档
  chunks       文档分块（INTEGER PK，便于与 vec 表 rowid 对齐）
  chunks_fts   FTS5 全文索引（存中文 bigram 化文本）
  vec_chunks   sqlite-vec 向量表（rowid = chunks.id）
  agent_runs   Agent 流程运行状态
  audit_logs   审计日志
"""
import os
import sqlite3
import sqlite_vec
import threading

from . import config

_local = threading.local()
_SCHEMA_READY = False


def connect() -> sqlite3.Connection:
    """线程/请求级连接（SQLite 连接不能跨线程共享）。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # ---- 并发与性能调优（SQLite 单文件多进程安全的关键）----
        # WAL：读写并发，读不阻塞写；synchronous=NORMAL：WAL 下仍崩溃一致且写入更快；
        # busy_timeout：写冲突时等待而非立即报 database is locked（多进程/多写者场景必备）；
        # cache_size=-16MB / temp_store=MEMORY：放大页缓存，显著降低重复查询 I/O。
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-16000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _local.conn = conn
    return conn


def _vec_table_sql(dim: int) -> str:
    return f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{dim}])"


def init_db(force_rebuild_vec: bool = False) -> None:
    """建表 + 兼容维度变更 + 种子默认租户/管理员。"""
    global _SCHEMA_READY
    conn = connect()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tenant_id, username)
        );
        CREATE TABLE IF NOT EXISTS docs(
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT,
            n_chunks INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_docs_tenant ON docs(tenant_id);
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_uid TEXT UNIQUE,
            tenant_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            seq INTEGER,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_uid UNINDEXED, tenant_id UNINDEXED, content, tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS agent_runs(
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            flow TEXT NOT NULL,
            current TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            state_json TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audit_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            actor TEXT,
            action TEXT,
            target TEXT,
            detail TEXT,
            ts TEXT DEFAULT (datetime('now'))
        );
        """
    )

    # 向量表：维度变更时重建（旧向量失效，需重新入库）
    if force_rebuild_vec:
        cur.execute("DROP TABLE IF EXISTS vec_chunks")
    cur.execute(_vec_table_sql(config.EMB_DIM))

    conn.commit()
    _seed()
    _SCHEMA_READY = True


def vec_version() -> str:
    try:
        return connect().execute("select vec_version()").fetchone()[0]
    except Exception as exc:  # pragma: no cover
        return f"unavailable: {exc}"


def _seed() -> None:
    """首次启动写入默认租户与管理员，避免空系统不可用。"""
    from .auth import hash_password

    conn = connect()
    row = conn.execute("SELECT id FROM tenants WHERE id='default'").fetchone()
    if not row:
        conn.execute("INSERT INTO tenants(id,name) VALUES('default','默认租户')")
    row = conn.execute("SELECT id FROM users WHERE tenant_id='default' AND username='admin'").fetchone()
    if not row:
        h, s = hash_password("admin123")
        conn.execute(
            "INSERT INTO users(id,tenant_id,username,password_hash,salt,role) VALUES(?,?,?,?,?,?)",
            ("u-admin", "default", "admin", h, s, "admin"),
        )
    conn.commit()


def audit(tenant_id: str, actor: str, action: str, target: str = "", detail: str = "") -> None:
    try:
        conn = connect()
        conn.execute(
            "INSERT INTO audit_logs(tenant_id,actor,action,target,detail) VALUES(?,?,?,?,?)",
            (tenant_id, actor, action, target, detail[:500]),
        )
        conn.commit()
    except Exception:
        pass
