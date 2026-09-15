"""M7 自进化引擎 + Curator（进化层刹车 · 对标 Hermes 自改进学习循环）。

设计：从会话经验 propose_skill 长出候选技能 → Curator 用黑名单 + 质量规则拦截"错误固化"
（对应 Hermes 黑名单：防止 Agent 学错后连月拒绝自己）→ 通过的技能可 save；prune 剪枝前
先备份到 skill_backups（Curator "动手先备份，永不删除"）。表均运行时建，不碰冻结 db.py。
零新增依赖。
"""
import json
import re
import uuid
from . import db

# Curator 黑名单：命中即视为"错误固化"倾向，拒绝沉淀为技能
BLACKLIST = ["一律拒绝", "永远不再", "永远拒绝", "全部驳回", "绝不处理", "never", "always reject", "一律不"]


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS evolved_skills(
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                name TEXT,
                description TEXT,
                body TEXT,
                triggers TEXT,
                status TEXT DEFAULT 'candidate',
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS skill_backups(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                skill_id TEXT,
                name TEXT,
                body TEXT,
                reason TEXT DEFAULT '',
                by TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def _keywords(text, top=6):
    words = re.findall(r"[一-龥]{2,4}", text)
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: -x[1])[:top]


def propose_skill(tenant_id, topic, sources: list, conn=None) -> dict:
    """从一组会话经验文本中蒸馏出候选技能（思维蒸馏型）。"""
    init(conn)
    blob = " ".join(sources)
    kws = _keywords(blob)
    triggers = "；".join("当问题涉及%s" % k for k, _ in kws[:3])
    body = "# %s 技能（自进化候选）\n\n## 经验来源\n" % topic
    body += "\n".join("- %s" % s[:60] for s in sources[:5])
    desc = "基于 %d 条会话经验沉淀的「%s」处理技能，触发条件：%s" % (len(sources), topic, triggers)
    return {"name": topic, "description": desc, "body": body, "triggers": triggers}


def curator_review(skill: dict) -> dict:
    """Curator 评审：黑名单拦截 + 质量规则（正文长度、触发条件）。返回 {accept, reason}。"""
    reasons = []
    body = (skill.get("body") or "") + (skill.get("description") or "")
    for bad in BLACKLIST:
        if bad.lower() in body.lower():
            reasons.append("命中 Curator 黑名单词：%s" % bad)
    if len(skill.get("body") or "") < 20:
        reasons.append("技能正文过短，疑似无效沉淀")
    if not skill.get("triggers"):
        reasons.append("缺少触发条件，无法被召回")
    return {"accept": len(reasons) == 0, "reason": "；".join(reasons) or "通过"}


def save_skill(tenant_id, skill: dict, conn=None) -> str:
    c = _conn(conn)
    init(c)
    sid = "sk_" + uuid.uuid4().hex[:12]
    c.execute(
        "INSERT INTO evolved_skills(id,tenant_id,name,description,body,triggers) VALUES(?,?,?,?,?,?)",
        (sid, tenant_id, skill["name"], skill["description"], skill["body"], skill["triggers"]),
    )
    c.commit()
    return sid


def get_skill(skill_id, conn=None):
    c = _conn(conn)
    init(c)
    r = c.execute("SELECT * FROM evolved_skills WHERE id=?", (skill_id,)).fetchone()
    return dict(r) if r else None


def prune(skill_id, reason="", by="", conn=None):
    """剪枝过时技能：Curator 原则——动手先备份，绝不静默删除。返回备份记录 id。"""
    c = _conn(conn)
    init(c)
    r = c.execute("SELECT * FROM evolved_skills WHERE id=?", (skill_id,)).fetchone()
    if not r:
        return None
    c.execute(
        "INSERT INTO skill_backups(tenant_id,skill_id,name,body,reason,by) VALUES(?,?,?,?,?,?)",
        (r["tenant_id"], skill_id, r["name"], r["body"], reason, by),
    )
    bk = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("DELETE FROM evolved_skills WHERE id=?", (skill_id,))
    c.commit()
    return bk


def list_skills(tenant_id, conn=None):
    c = _conn(conn)
    init(c)
    rows = c.execute("SELECT * FROM evolved_skills WHERE tenant_id=?", (tenant_id,)).fetchall()
    return [dict(r) for r in rows]
