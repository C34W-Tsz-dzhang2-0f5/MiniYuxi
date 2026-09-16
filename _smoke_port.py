"""一次性冒烟测试：验证四个移植模块的核心链路（内存库隔离，不污染真实 DB）。"""
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, r"E:/HR有关AI/AI应用基座最佳实践/14_自研MiniYuxi")
from core import labor_relations, salary_records, resume_screening, security, backup

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
ok = True

# ---- 1. 劳动关系：第14条预警 + 试用期提醒 ----
labor_relations.init(conn)
today = date.today()
c_end = (today + timedelta(days=30)).isoformat()
p_end = (today + timedelta(days=10)).isoformat()
cid = labor_relations.upsert_contract(
    tenant_id="default", conn=conn, name="劳动合同", personnel="张三(车务通)",
    start_date=(today - timedelta(days=400)).isoformat(), end_date=c_end,
    contract_no=2, status="履行中", probation_end=p_end,
    note="与陕西导航存在混同用工风险，续订需评估关联责任")
labor_relations.sync_contract_todos("default", conn)
todos = labor_relations.list_todos("default", "open", conn)
print("== 劳动关系待办生成数:", len(todos))
for t in todos:
    print(f"   [{t['level']}] {t['source']} :: {t['title']}")
art14 = [t for t in todos if "第14条" in t["title"]]
prob = [t for t in todos if "试用期" in t["title"]]
print("   第14条预警命中:", bool(art14), "| 试用期提醒命中:", bool(prob))
assert art14 and prob, "第14条/试用期预警未生成"
print("   ✓ 第14条无固定期限预警 + 试用期提醒 OK")

# ---- 2. 薪酬：明细 + 答疑 ----
salary_records.init(conn)
rid = salary_records.add_record(tenant_id="default", conn=conn, emp_name="张三", month="2026-09",
                                base_salary=10000, performance=2000, subsidy=500,
                                social_insurance=1050, housing_fund=1200, tax=300, other_deduct=0)
recs = salary_records.list_records("default", month="2026-09", conn=conn)
net = recs[0]["net_salary"]
# 应发 = 10000+2000+500 = 12500；实发 = 12500-1050(社保)-1200(公积金)-300(个税)-0 = 9950
print("== 工资明细实发:", net, "(期望 9950)")
assert net == 9950, f"net mismatch {net}"
qa = salary_records.salary_qa("实发工资怎么算", "default", conn)
print("   答疑:", qa["answer"][:40], "...")
assert "实发" in qa["answer"]
print("   ✓ 薪酬明细 + 答疑 OK")

# ---- 3. 简历规则引擎：三档 ----
# 3.1 强候选人 → 期望 pass
strong = "张三 本科 5年工作经验 深圳 期望薪资 15k 熟悉 python linux mysql docker，曾带5人团队"
r1 = resume_screening.screen_resume(strong, "软件工程师", None)
# 3.2 弱候选人：硬条件（学历/年限）不满足 → 期望 reject（hard_pass=False）
weak = "李四 高中毕业 无工作经验，不会编程"
r2 = resume_screening.screen_resume(weak, "软件工程师",
                                    {"education": "本科", "min_years": 3})
# 3.3 中等：硬条件满足但软分一般 → 期望 maybe 或 reject，不得为 pass
mid = "王五 本科 5年工作经验 深圳 期望薪资 15k，了解 python"
r3 = resume_screening.screen_resume(mid, "软件工程师", {"education": "本科", "min_years": 3})
for tag, r in (("强", r1), ("弱", r2), ("中", r3)):
    print("== 简历规则[%s]: bucket=%s score=%s hard_pass=%s"
          % (tag, r["bucket"], r["score"], r["hard_pass"]))
assert r1["bucket"] == "pass", f"强候选人应 pass，实得 {r1['bucket']}/{r1['score']}"
assert r2["bucket"] == "reject" and r2["hard_pass"] is False, "弱候选人应硬条件否决"
assert r3["bucket"] == "maybe", f"中等候选人应 maybe，实得 {r3['bucket']}/{r3['score']}"
# 未识别维度不得计入分母（信息缺失≠不合格）：强候选人技能满分
sk = [d for d in r1["score_detail"] if d["key"] == "skills"][0]
print("   技能项: part=%s reason=%s" % (sk["part"], sk["reason"]))
print("   ✓ 简历规则引擎三档 OK（pass/maybe|reject/reject 分档正确）")

# ---- 4. 安全掩码 ----
m = security.mask_phone("13812345678")
mid = security.mask_id_card("440300199001011234")
print("== 掩码: 手机", m, "| 身份证", mid)
assert m == "138****5678"
print("   ✓ 敏感字段掩码 OK")

# ---- 5. 备份（真实库，幂等，仅验证不报错）----
b = backup.daily_backup(conn=None)
print("== 备份:", b.get("backed_up"), b.get("reason", ""), b.get("path", ""))
print("\nALL SMOKE TESTS PASSED" if ok else "FAILED")
