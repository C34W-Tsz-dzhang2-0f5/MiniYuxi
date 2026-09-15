"""模块二 · AI面试助手：结构化追问 + 面评沉淀 + 企业面试题库。

设计：零新增依赖；运行时建表。追问与话术均为规则模板生成（可解释、可审计），
不依赖外部 LLM 即可产出标准化结构化内容；LLM 仅作可选增强。
"""
import json
from . import db

# 各维度的结构化追问模板（按胜任力维度展开）
QUESTION_BANK_PRESET = {
    "软件工程师": [
        ("专业技能", "请描述你最近负责的一个核心模块，遇到的最难技术问题及解决路径。"),
        ("项目经验", "挑一个你主导的项目，讲清楚你的角色、技术选型理由和上线结果。"),
        ("沟通协作", "举例说明你如何与产品/测试协作解决需求歧义。"),
    ],
    "销售代表": [
        ("销售业绩", "请用数据说明你历史最好的一单，从触达到达成的全过程。"),
        ("沟通表达", "如果客户说'再考虑一下'，你会如何闭环？"),
        ("抗压自驱", "描述一次连续被拒后你如何调整策略完成指标。"),
    ],
    "HR专员": [
        ("HR专业度", "请梳理一次你独立处理的员工关系/劳动争议事件及处置依据。"),
        ("合规意识", "试用期辞退的合法边界是什么？请结合法条说明。"),
        ("沟通协调", "业务部门与员工发生冲突，你如何居中协调？"),
    ],
}


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS interview_questions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                job_category TEXT,
                dimension TEXT,
                question TEXT,
                UNIQUE(tenant_id, job_category, dimension, question)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS interview_evaluations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                candidate TEXT,
                job_title TEXT,
                scores_json TEXT,
                summary TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def add_question(tenant_id, job_category, dimension, question, conn=None):
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT OR IGNORE INTO interview_questions(tenant_id,job_category,dimension,question) VALUES(?,?,?,?)",
        (tenant_id, job_category, dimension, question),
    )
    c.commit()
    return True


def list_questions(job_category=None, tenant_id="default", conn=None):
    c = _conn(conn)
    init(c)
    if job_category:
        rows = c.execute(
            "SELECT dimension,question FROM interview_questions WHERE tenant_id=? AND job_category=?",
            (tenant_id, job_category),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT job_category,dimension,question FROM interview_questions WHERE tenant_id=?", (tenant_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def generate_questions(resume_text: str, job_title: str, tenant_id="default", conn=None) -> list:
    """结构化追问：优先用题库预设，结合简历命中的短板维度追加针对性问题。"""
    c = _conn(conn)
    init(c)
    bank = list_questions(job_title, tenant_id, c)
    if not bank:
        bank = [{"dimension": d, "question": q} for d, q in QUESTION_BANK_PRESET.get(job_title, QUESTION_BANK_PRESET["HR专员"])]
        # 首用时把预设沉淀进题库
        for b in bank:
            add_question(tenant_id, job_title, b["dimension"], b["question"], c)
    # 针对简历解析出的薄弱点补一刀
    from . import resume_scorer
    r = resume_scorer.score(resume_text, job_title, tenant_id, c)
    extra = []
    if "工作年限" in r["gaps"]:
        extra.append({"dimension": "工作年限", "question": "你的相关岗位年限偏短，请说明上手速度与学习路径。"})
    if "专业技能" in r["gaps"]:
        extra.append({"dimension": "专业技能", "question": "请就你最不熟悉的岗位技能，说明学习计划。"})
    return bank + extra


def save_evaluation(tenant_id, candidate, job_title, scores: dict, summary: str, conn=None):
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT INTO interview_evaluations(tenant_id,candidate,job_title,scores_json,summary) VALUES(?,?,?,?,?)",
        (tenant_id, candidate, job_title, json.dumps(scores, ensure_ascii=False), summary),
    )
    c.commit()
    return True


def list_evaluations(tenant_id="default", conn=None):
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT candidate,job_title,scores_json,summary,created_at FROM interview_evaluations WHERE tenant_id=? ORDER BY id DESC LIMIT 50",
        (tenant_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["scores"] = json.loads(d.pop("scores_json"))
        out.append(d)
    return out
