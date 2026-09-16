"""HTTP 层端到端冒烟：劳动关系 / 薪酬 / 技能抽屉桥接。

用 FastAPI TestClient 直连 app（无需另起端口），admin token 覆盖写权限。
注意：会向真实 data/miniyuxi.db 写入少量测试数据，脚本末尾自动清理。
"""
import sys
from datetime import date, timedelta

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
from core import auth, db, labor_relations, salary_records  # noqa: E402

TOKEN = auth.make_token({"tid": "default", "sub": "smoke", "role": "admin"})
H = {"Authorization": "Bearer " + TOKEN}
client = TestClient(api.app)

ok = True


def chk(label, cond, extra=""):
    global ok
    flag = "✓" if cond else "✗"
    if not cond:
        ok = False
    print("   %s %s %s" % (flag, label, extra))


def get(path, **params):
    return client.get(path, headers=H, params=params)


def post(path, json=None):
    return client.post(path, headers=H, json=json or {})


print("== 1. 鉴权基线")
r = get("/api/labor/dashboard")
chk("GET /api/labor/dashboard 200", r.status_code == 200, str(r.status_code))
chk("无 token 应 401", client.get("/api/labor/dashboard").status_code == 401)

print("== 2. 劳动关系：建合同 → 同步 → 待办")
today = date.today()
payload = {
    "name": "劳动合同", "personnel": "冒烟测试员",
    "start_date": (today - timedelta(days=400)).isoformat(),
    "end_date": (today + timedelta(days=30)).isoformat(),
    "contract_no": 2, "status": "履行中",
    "probation_end": (today + timedelta(days=10)).isoformat(),
    "note": "HTTP 冒烟临时数据",
}
r = post("/api/labor/contracts", payload)
chk("POST /api/labor/contracts 200", r.status_code == 200, str(r.status_code))
cid = (r.json() or {}).get("id")
chk("返回合同 id", bool(cid), str(cid))

r = post("/api/labor/sync")
chk("POST /api/labor/sync 200", r.status_code == 200, str(r.status_code))
r = get("/api/labor/todos", status="open")
todos = (r.json() or {}).get("todos", [])
chk("生成待办 >= 3 条", len(todos) >= 3, "实际 %d 条" % len(todos))
titles = " | ".join(t["title"] for t in todos)
chk("含第14条预警", "第14条" in titles)
chk("含试用期提醒", "试用期" in titles)

r = get("/api/labor/dashboard")
dash = r.json() or {}
chk("dashboard 含统计", isinstance(dash, dict) and len(dash) > 0, str(list(dash)[:5]))

# 解决一条待办
if todos:
    tid = todos[0]["id"]
    r = post(f"/api/labor/todos/{tid}/resolve")
    chk("POST resolve 待办 200", r.status_code == 200, str(r.status_code))
    left = get("/api/labor/todos", status="open").json().get("todos", [])
    chk("解决后 open 数减少", len(left) == len(todos) - 1,
        "%d -> %d" % (len(todos), len(left)))

print("== 3. 薪酬：明细 → 汇总 → 答疑")
sp = {"emp_name": "冒烟测试员", "month": "2026-09", "base_salary": 10000,
      "performance": 2000, "subsidy": 500, "social_insurance": 1050,
      "housing_fund": 1200, "tax": 300, "other_deduct": 0}
r = post("/api/salary/records", sp)
chk("POST /api/salary/records 200", r.status_code == 200, str(r.status_code))
r = get("/api/salary/records", month="2026-09")
recs = (r.json() or {}).get("records", [])
chk("明细可读", len(recs) >= 1, "%d 条" % len(recs))
chk("实发 = 9950", recs and recs[0].get("net_salary") == 9950,
    str(recs[0].get("net_salary")) if recs else "空")
r = get("/api/salary/summary", month="2026-09")
chk("GET /api/salary/summary 200", r.status_code == 200, str(r.status_code))
r = post("/api/salary/qa", {"question": "实发工资怎么算"})
ans = (r.json() or {}).get("answer", "")
chk("答疑含公式", "实发" in ans, ans[:30])

print("== 4. 技能抽屉桥接（folder skill 可点选）")
r = get("/api/skills/list")
skills = (r.json() or {}).get("skills", [])
folders = [s for s in skills if s.get("type") == "folder"]
chk("skills/list 200", r.status_code == 200, str(r.status_code))
chk("含 folder 类型技能", len(folders) > 0, "%d/%d 条" % (len(folders), len(skills)))
chk("folder 技能带 name/description",
    bool(folders) and all(f.get("name") and f.get("description") for f in folders[:5]))
chk("hr-resume 在列", any(f.get("name") == "hr-resume" for f in folders))

# ---- 清理测试数据 ----
conn = db.connect()
try:
    conn.execute("DELETE FROM labor_todos")
    conn.execute("DELETE FROM contracts")
    conn.execute("DELETE FROM salary_records")
    conn.commit()
    print("   已清理冒烟测试数据")
except Exception as e:
    print("   清理失败（可手动清）:", e)
finally:
    conn.close()

print("\nHTTP SMOKE PASSED" if ok else "\nHTTP SMOKE FAILED")
sys.exit(0 if ok else 1)
