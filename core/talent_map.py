"""模块五 · 人才地图自动化：同行人才资源池 + 岗位未开、人才先行。

设计：零新增依赖；运行时建表。talent_pool 记录同行人才（公司/职位/领域/状态），
支持按目标公司/领域检索与统计；proactive 储备标记实现"人才先行"。
"""
import json
from . import db


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS talent_pool(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                name TEXT,
                company TEXT,
                title TEXT,
                domain TEXT,
                tags TEXT,
                status TEXT DEFAULT '储备',
                source TEXT,
                last_updated TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def add_talent(tenant_id, name, company, title, domain, tags="", status="储备", source="", conn=None):
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT INTO talent_pool(tenant_id,name,company,title,domain,tags,status,source) VALUES(?,?,?,?,?,?,?,?)",
        (tenant_id, name, company, title, domain, tags, status, source),
    )
    c.commit()
    return True


def list_by_domain(domain, tenant_id="default", conn=None):
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT name,company,title,status,tags FROM talent_pool WHERE tenant_id=? AND domain=? ORDER BY id DESC",
        (tenant_id, domain),
    ).fetchall()
    return [dict(r) for r in rows]


def list_by_company(company, tenant_id="default", conn=None):
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT name,title,domain,status FROM talent_pool WHERE tenant_id=? AND company=? ORDER BY id DESC",
        (tenant_id, company),
    ).fetchall()
    return [dict(r) for r in rows]


def stats(tenant_id="default", conn=None):
    c = _conn(conn)
    init(c)
    by_company = c.execute(
        "SELECT company, COUNT(*) n FROM talent_pool WHERE tenant_id=? GROUP BY company ORDER BY n DESC LIMIT 10",
        (tenant_id,),
    ).fetchall()
    by_domain = c.execute(
        "SELECT domain, COUNT(*) n FROM talent_pool WHERE tenant_id=? GROUP BY domain ORDER BY n DESC",
        (tenant_id,),
    ).fetchall()
    reserve = c.execute(
        "SELECT COUNT(*) n FROM talent_pool WHERE tenant_id=? AND status='储备'", (tenant_id,)
    ).fetchone()["n"]
    total = c.execute("SELECT COUNT(*) n FROM talent_pool WHERE tenant_id=?", (tenant_id,)).fetchone()["n"]
    return {
        "total": total, "储备数": reserve,
        "by_company": [dict(r) for r in by_company],
        "by_domain": [dict(r) for r in by_domain],
    }


def suggest_for_role(role_domain, tenant_id="default", conn=None):
    """岗位未开、人才先行：返回该领域已储备人才清单，供提前触达。"""
    return list_by_domain(role_domain, tenant_id, conn)
