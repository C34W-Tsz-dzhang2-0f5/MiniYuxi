"""M2 审批卡（HITL 约束层）：高危工具调用前挂起 → 审批卡 → 断点续跑。

设计：approvals 表运行时建（不碰冻结 db.py）。状态机 pending → approved / rejected。
断点续跑 token（resume_token）随审批单持久化，审批通过后原调用方可据此恢复执行。
"""
import uuid
from . import db

# 命门级工具：默认"每次询问"挂起审批卡
ASK_EVERY_TIME = {"kb.delete", "kb.upload", "mcp.write", "tenant.manage", "user.manage", "agent.run"}
# 其余中危工具：按 risk 字段评估
RISK_TOOLS = {"kb.delete", "mcp.write", "agent.run", "tenant.manage", "user.manage"}


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS approvals(
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                tool_name TEXT,
                args_json TEXT DEFAULT '{}',
                requested_by TEXT DEFAULT '',
                risk TEXT DEFAULT 'high',
                status TEXT DEFAULT 'pending',
                decision_by TEXT DEFAULT '',
                decision_note TEXT DEFAULT '',
                resume_token TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                decided_at TEXT DEFAULT ''
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def needs_approval(tool_name: str) -> bool:
    """该工具调用是否需挂起审批卡。"""
    return tool_name in ASK_EVERY_TIME or tool_name in RISK_TOOLS


def create(tenant_id, tool_name, args_json="{}", requested_by="", risk="high",
            resume_token="", conn=None) -> str:
    c = _conn(conn)
    init(c)
    aid = "ap_" + uuid.uuid4().hex[:12]
    c.execute(
        "INSERT INTO approvals(id,tenant_id,tool_name,args_json,requested_by,risk,resume_token) "
        "VALUES(?,?,?,?,?,?,?)",
        (aid, tenant_id, tool_name, args_json, requested_by, risk, resume_token),
    )
    c.commit()
    return aid


def decide(approval_id, approve: bool, by="", note="", conn=None) -> dict:
    c = _conn(conn)
    init(c)
    status = "approved" if approve else "rejected"
    c.execute(
        "UPDATE approvals SET status=?, decision_by=?, decision_note=?, decided_at=datetime('now') "
        "WHERE id=?",
        (status, by, note, approval_id),
    )
    c.commit()
    return get(approval_id, c)


def get(approval_id, conn=None):
    c = _conn(conn)
    init(c)
    r = c.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    return dict(r) if r else None


def list_pending(tenant_id, conn=None):
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT * FROM approvals WHERE tenant_id=? AND status='pending' ORDER BY id DESC",
        (tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]
