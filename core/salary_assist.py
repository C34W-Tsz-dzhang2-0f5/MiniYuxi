"""模块四 · 谈薪辅助：基于岗位预算 + 市场分位，生成谈薪策略与话术。

设计：零新增依赖；运行时建表。市场分位(p25/p50/p75)可录入/更新；
advise 在「不超预算」前提下给出市场定位、建议区间与可直接照念的话术。
"""
import json
from . import db


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS salary_market(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                job_title TEXT,
                p25 REAL, p50 REAL, p75 REAL,
                UNIQUE(tenant_id, job_title)
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def set_market(tenant_id, job_title, p25, p50, p75, conn=None):
    c = _conn(conn)
    init(c)
    c.execute(
        "INSERT OR REPLACE INTO salary_market(tenant_id,job_title,p25,p50,p75) VALUES(?,?,?,?,?)",
        (tenant_id, job_title, float(p25), float(p50), float(p75)),
    )
    c.commit()
    return True


def get_market(tenant_id, job_title, conn=None):
    c = _conn(conn)
    init(c)
    row = c.execute(
        "SELECT p25,p50,p75 FROM salary_market WHERE tenant_id=? AND job_title=?", (tenant_id, job_title)
    ).fetchone()
    return dict(row) if row else None


def advise(job_title, budget, candidate_level="mid", tenant_id="default", conn=None) -> dict:
    """candidate_level: junior/mid/senior。返回定位、建议区间、话术。"""
    mkt = get_market(tenant_id, job_title, conn)
    budget = float(budget)
    if not mkt:
        return {"ok": False, "msg": "未配置该岗位市场分位数据，请先 set_market。"}
    p25, p50, p75 = mkt["p25"], mkt["p50"], mkt["p75"]
    # 目标锚点：初级看 p25-p50，中级看 p50，高级看 p75
    anchor = {"junior": (p25, p50), "mid": (p50, p75), "senior": (p75, p75 * 1.15)}[candidate_level]
    low, high = anchor
    # 预算约束：不超过预算；若预算低于市场，需提示风险
    if budget < low:
        position = "低于市场"
        recommended = round(budget)
        note = f"预算 {budget} 低于市场 {candidate_level} 区间下限 {round(low)}，存在招人风险。"
    elif budget > high:
        position = "高于市场"
        recommended = round(min(budget, high * 1.05))
        note = f"预算充足，建议锚定市场高位 {round(high)} 以抢人。"
    else:
        position = "持平市场"
        recommended = round((low + high) / 2)
        note = f"预算落在市场 {candidate_level} 区间内，建议中位 {recommended}。"
    scripts = [
        f"我们非常认可你的能力，结合岗位预算与市场水平，初步薪酬定在 {recommended}（{position}）。",
        f"这个数字是综合了你{('初级' if candidate_level=='junior' else '中级' if candidate_level=='mid' else '高级')}定位和深圳同岗分位给到的，后续绩效优秀还有上浮空间。",
        f"如果对其他构成（绩效/补贴）有偏好，我们可以一起拆开看，总包不变的前提下做结构优化。",
    ]
    return {
        "ok": True, "job_title": job_title, "candidate_level": candidate_level,
        "market": mkt, "position": position, "recommended": recommended,
        "budget": budget, "band": [round(low), round(high)], "note": note,
        "scripts": scripts,
    }
