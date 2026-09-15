"""闭环学习最小版（T6）：对话后抽取经验写入 skills 表（抄 Hermes 闭环，简化）。

不自动改 prompt：仅把"问了什么 + 答案中的关键事实"沉淀为可检索技能，供 /api/skills/list 复盘。
抽取策略：取答案中信息量较高的前若干句作为经验文本（真实内容，非模板废话）。
"""
import re
from . import db


def init():
    try:
        conn = db.connect()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS skills(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                question TEXT,
                skill_text TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        conn.commit()
    except Exception:
        pass


def _extract(answer: str) -> str:
    if not answer:
        return ""
    text = re.sub(r"\[?\d+\]?", "", answer)
    text = re.sub(r"[【】（】\)#\*`>]", " ", text)
    sents = [s.strip() for s in re.split(r"[。！？\n!?]", text) if len(s.strip()) >= 6]
    return "；".join(sents[:3])


def learn(tenant_id, question, answer) -> None:
    try:
        skill = _extract(answer)
        if not skill:
            return
        init()
        conn = db.connect()
        conn.execute(
            "INSERT INTO skills(tenant_id,question,skill_text) VALUES(?,?,?)",
            (tenant_id, (question or "")[:300], skill[:800]),
        )
        conn.commit()
    except Exception:
        pass


def list_skills(tenant_id=None, limit=50) -> list:
    try:
        init()
        conn = db.connect()
        where = "WHERE tenant_id=?" if tenant_id else ""
        params = (tenant_id,) if tenant_id else ()
        rows = conn.execute(
            f"SELECT id,question,skill_text,created_at FROM skills {where} ORDER BY id DESC LIMIT ?",
            params + (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
