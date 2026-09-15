"""M4 记忆深化（三层记忆）：会话 / 长期 / 经验蒸馏。

设计：复用 memory.py 的 memories 表做长期记忆；新增 experiences 表沉淀"经验"，
distill() 按高频关键词把零散经验聚合成可复用的沉淀笔记（经验→Skill 的雏形）。
零新增依赖；表均运行时 CREATE TABLE IF NOT EXISTS。
"""
import re
from . import db, memory

_STOP = set("的 了 是 在 和 与 或 及 对 等 该 其 我 你 他 她 它 我们 他们 她们 这个 那个".split())


def init(conn=None):
    memory.init()  # 复用长期记忆表
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS experiences(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                text TEXT,
                source TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def append_experience(tenant_id, text, source="", conn=None):
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT INTO experiences(tenant_id,text,source) VALUES(?,?,?)",
        (tenant_id, text[:2000], source),
    )
    c.commit()


def _keywords(text, top=5):
    words = re.findall(r"[一-龥]{2,6}", text)
    freq = {}
    for w in words:
        if w in _STOP:
            continue
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: -x[1])[:top]


def distill(tenant_id, top_n=3, conn=None) -> list:
    """经验蒸馏：把 experiences 按首高频关键词归并，生成带命中数的沉淀笔记。"""
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT id,text FROM experiences WHERE tenant_id=? ORDER BY id DESC LIMIT 200",
        (tenant_id,),
    ).fetchall()
    cluster = {}
    for r in rows:
        kws = _keywords(r["text"])
        if not kws:
            continue
        key = kws[0][0]
        cluster.setdefault(key, []).append(r["text"])
    notes = []
    for topic, texts in cluster.items():
        notes.append(
            {
                "topic": topic,
                "hits": len(texts),
                "note": "「%s」共 %d 条经验；要点：%s"
                % (topic, len(texts), "；".join(t[:40] for t in texts[:3])),
            }
        )
    notes.sort(key=lambda x: -x["hits"])
    return notes[:top_n]
