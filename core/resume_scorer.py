"""模块一 · AI简历评分卡与岗位胜任力模型。

设计：零新增依赖；新表走运行时 CREATE TABLE IF NOT EXISTS，不碰冻结 db.py。
所有函数 conn=None 默认，便于单测用 :memory:；核心算法为规则 + 可解释权重，
不依赖外部 LLM 即可跑通（LLM 仅作可选增强，缺失 Key 不阻断）。
"""
import json
import re
from . import db

# 岗位胜任力预设权重（覆盖式，可在库内覆盖/新增）
COMPETENCY_PRESETS = {
    "软件工程师": {"学历": 0.15, "工作年限": 0.25, "专业技能": 0.35, "项目经验": 0.15, "沟通协作": 0.10},
    "销售代表": {"学历": 0.10, "工作年限": 0.20, "销售业绩": 0.35, "沟通表达": 0.25, "抗压自驱": 0.10},
    "HR专员": {"学历": 0.15, "工作年限": 0.20, "HR专业度": 0.30, "沟通协调": 0.25, "合规意识": 0.10},
    "通用岗位": {"学历": 0.15, "工作年限": 0.25, "专业技能": 0.30, "相关经验": 0.20, "软素质": 0.10},
}

EDU_RANK = {"博士": 4, "硕士": 3, "本科": 2, "大专": 1, "中专": 0, "高中": 0}
SKILL_LEXICON = {
    "软件工程师": ["python", "java", "go", "c++", "react", "vue", "linux", "mysql", "redis", "docker", "k8s", "算法", "数据结构"],
    "销售代表": ["bd", "大客户", "渠道", "签单", "陌拜", "crm", "谈判", "回款"],
    "HR专员": ["招聘", "绩效", "薪酬", "员工关系", "劳动争议", "社保", "劳动合同法", "培训", "组织发展"],
}


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS competency(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                job_title TEXT,
                weights_json TEXT,
                UNIQUE(tenant_id, job_title)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                name TEXT,
                job_title TEXT,
                resume_text TEXT,
                score REAL DEFAULT 0,
                subscores_json TEXT,
                ranked_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def save_competency(tenant_id, job_title, weights: dict, conn=None):
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT OR REPLACE INTO competency(tenant_id, job_title, weights_json) VALUES(?,?,?)",
        (tenant_id, job_title, json.dumps(weights, ensure_ascii=False)),
    )
    c.commit()
    return True


def get_competency(tenant_id, job_title, conn=None):
    c = _conn(conn)
    init(c)
    row = c.execute(
        "SELECT weights_json FROM competency WHERE tenant_id=? AND job_title=?", (tenant_id, job_title)
    ).fetchone()
    if row:
        return json.loads(row["weights_json"])
    return COMPETENCY_PRESETS.get(job_title, COMPETENCY_PRESETS["通用岗位"])


def parse_resume(text: str) -> dict:
    """轻量解析：学历、工作年限、技能命中。规则可解释，便于出庭/复核。"""
    t = (text or "").lower()
    edu = 0
    for k, v in EDU_RANK.items():
        if k in t and v > edu:
            edu = v
    years = 0
    for m in re.finditer(r"(\d{1,2})\s*年", t):
        years = max(years, int(m.group(1)))
    # 技能命中：按通用词表粗略匹配
    skills_hit = [s for s in sum(SKILL_LEXICON.values(), []) if s in t]
    return {"edu": edu, "years": years, "skills": skills_hit, "skill_count": len(skills_hit)}


def _subscore(feature: dict, job_title: str) -> dict:
    s = {}
    s["学历"] = min(100, feature["edu"] / 4 * 100)
    s["工作年限"] = min(100, feature["years"] / 8 * 100)
    s["专业技能"] = min(100, feature["skill_count"] / 8 * 100)
    s["项目经验"] = min(100, feature["skill_count"] / 6 * 100)
    s["沟通协作"] = min(100, 40 + feature["skill_count"] * 5)
    s["沟通表达"] = min(100, 40 + feature["skill_count"] * 6)
    s["销售业绩"] = min(100, 30 + feature["years"] * 8)
    s["沟通协调"] = min(100, 40 + feature["years"] * 6)
    s["合规意识"] = min(100, 50 + feature["edu"] * 10)
    s["相关经验"] = min(100, feature["years"] / 6 * 100)
    s["HR专业度"] = min(100, 30 + feature["skill_count"] * 8)
    s["抗压自驱"] = min(100, 40 + feature["years"] * 7)
    s["软素质"] = min(100, 45 + feature["edu"] * 8)
    return s


def score(resume_text: str, job_title: str, tenant_id=None, conn=None) -> dict:
    """返回 {score, subscores, matched_skills, gaps}。score 为 0-100 加权总分。"""
    weights = get_competency(tenant_id or "default", job_title, conn)
    feat = parse_resume(resume_text)
    subs = _subscore(feat, job_title)
    total = 0.0
    for dim, w in weights.items():
        total += subs.get(dim, 0) * w
    total = round(total, 1)
    gaps = [d for d, w in weights.items() if subs.get(d, 0) < 50 and w >= 0.2]
    return {
        "score": total,
        "subscores": {d: round(subs.get(d, 0), 1) for d in weights},
        "matched_skills": feat["skills"],
        "gaps": gaps,
        "level": "A" if total >= 80 else ("B" if total >= 65 else ("C" if total >= 50 else "D")),
    }


def rank_candidates(items: list, job_title: str, tenant_id="default", conn=None) -> list:
    """items: [{"name", "resume_text"}] → 按 score 降序返回带 rank。可选落库 candidates。"""
    c = _conn(conn)
    init(c)
    out = []
    for it in items:
        r = score(it["resume_text"], job_title, tenant_id, c)
        out.append({"name": it.get("name", ""), **r})
        if tenant_id:
            c.execute(
                "INSERT INTO candidates(tenant_id,name,job_title,resume_text,score,subscores_json) VALUES(?,?,?,?,?,?)",
                (tenant_id, it.get("name", ""), job_title, it.get("resume_text", ""), r["score"], json.dumps(r["subscores"], ensure_ascii=False)),
            )
    c.commit()
    out.sort(key=lambda x: x["score"], reverse=True)
    for i, o in enumerate(out, 1):
        o["rank"] = i
    return out
