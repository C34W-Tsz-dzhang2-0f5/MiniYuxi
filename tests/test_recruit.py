"""招聘智能系统 5 模块单元测试（TDD 绿阶段）。

隔离：全部用 :memory: 连接，不触碰生产库。运行：python test_recruit.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import resume_scorer, interview, recruit_dashboard, salary_assist, talent_map

TID = "ut_tenant"


def fresh():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for m in (resume_scorer, interview, recruit_dashboard, salary_assist, talent_map):
        m.init(c)
    return c


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAIL: {name}")
    print(f"  ok  {name}")


def test_resume_scorer():
    c = fresh()
    r = resume_scorer.score("本科，5年python开发经验，熟悉mysql redis docker k8s", "软件工程师", TID, c)
    check("score in 0-100", 0 <= r["score"] <= 100)
    check("has level", r["level"] in "ABCD")
    check("matched skills", len(r["matched_skills"]) >= 1)
    items = [
        {"name": "甲", "resume_text": "硕士，8年java经验，熟悉mysql redis docker k8s 算法 数据结构"},
        {"name": "乙", "resume_text": "大专，1年实习，会一点python"},
    ]
    ranked = resume_scorer.rank_candidates(items, "软件工程师", TID, c)
    check("rank desc", ranked[0]["score"] >= ranked[1]["score"])
    check("rank assigned", ranked[0]["rank"] == 1 and ranked[1]["rank"] == 2)


def test_interview():
    c = fresh()
    qs = interview.generate_questions("本科，2年销售，bd 大客户 回款", "销售代表", TID, c)
    check("questions structured", all("dimension" in q and "question" in q for q in qs))
    bank = interview.list_questions("销售代表", TID, c)
    check("bank persisted", len(bank) >= 1)
    interview.save_evaluation(TID, "张三", "销售代表", {"沟通表达": 80}, "表达清晰，需补数据", c)
    evs = interview.list_evaluations(TID, c)
    check("evaluation saved", evs and evs[0]["candidate"] == "张三")


def test_dashboard_gap():
    c = fresh()
    for st, n in [("简历", 100), ("初筛", 60), ("面试", 30), ("offer", 10), ("到岗", 3)]:
        recruit_dashboard.record(TID, "W36", st, n, c)
    d = recruit_dashboard.weekly(TID, "W36", c)
    check("weekly funnel", d["offer"] == 10 and d["到岗"] == 3)
    g = recruit_dashboard.detect_gap(TID, "W36", conn=c)
    check("gap alert triggered", len(g["alerts"]) == 1 and "断档" in g["alerts"][0]["msg"])
    # 健康周不应预警
    for st, n in [("简历", 100), ("初筛", 60), ("面试", 30), ("offer", 10), ("到岗", 9)]:
        recruit_dashboard.record(TID, "W37", st, n, c)
    g2 = recruit_dashboard.detect_gap(TID, "W37", conn=c)
    check("no false alert", len(g2["alerts"]) == 0)


def test_salary():
    c = fresh()
    salary_assist.set_market(TID, "软件工程师", 15, 20, 28, c)
    a = salary_assist.advise("软件工程师", 22, "mid", TID, c)
    check("advise ok", a["ok"] and a["position"] == "持平市场")
    check("scripts present", len(a["scripts"]) == 3)
    b = salary_assist.advise("软件工程师", 10, "mid", TID, c)
    check("budget below market flagged", b["position"] == "低于市场")
    miss = salary_assist.advise("算法工程师", 22, "mid", TID, c)
    check("missing market handled", miss["ok"] is False)


def test_talent_map():
    c = fresh()
    talent_map.add_talent(TID, "李四", "竞品A", "高级工程师", "自动驾驶", "感知", source="猎头", conn=c)
    talent_map.add_talent(TID, "王五", "竞品A", "工程师", "自动驾驶", "规划", status="储备", conn=c)
    by_c = talent_map.list_by_company("竞品A", TID, c)
    check("by company", len(by_c) == 2)
    by_d = talent_map.list_by_domain("自动驾驶", TID, c)
    check("by domain", len(by_d) == 2)
    st = talent_map.stats(TID, c)
    check("stats total", st["total"] == 2 and st["储备数"] == 2)
    sug = talent_map.suggest_for_role("自动驾驶", TID, c)
    check("proactive suggest", len(sug) == 2)


if __name__ == "__main__":
    test_resume_scorer()
    test_interview()
    test_dashboard_gap()
    test_salary()
    test_talent_map()
    print("\nALL_OK  (5/5 招聘模块测试通过)")
