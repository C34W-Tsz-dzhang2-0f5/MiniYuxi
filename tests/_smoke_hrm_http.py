"""HRM 人事管理系统 HTTP 层端到端冒烟（FastAPI TestClient，不占端口）。

覆盖：表单清单 / 结构 / 中文标签建单 / 子表单 / 更新 / 审批流 / 通配路由顺序 / 错误码。
用临时库，不污染 data/miniyuxi.db。

用法（项目根目录）：
    python tests/_smoke_hrm_http.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.gettempdir(), "hrm_http_smoke.db")
if os.path.exists(_tmp):
    try:
        os.remove(_tmp)
    except OSError:
        pass
os.environ["MINIYUXI_DB"] = _tmp

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
from core import auth  # noqa: E402

TOKEN = auth.make_token({"tid": "default", "sub": "hrm_smoke", "role": "admin"})
H = {"Authorization": "Bearer " + TOKEN}
client = TestClient(api.app)

PASS = FAIL = 0


def chk(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("   ✓ %s %s" % (label, extra))
    else:
        FAIL += 1
        print("   ✗ %s %s" % (label, extra))


print("== 1. 元信息")
r = client.get("/api/hrm/forms", headers=H)
chk("GET /api/hrm/forms 200", r.status_code == 200, f"({r.status_code})")
forms = r.json().get("forms", []) if r.status_code == 200 else []
chk("表单数=49", len(forms) == 49, f"(实际 {len(forms)})")
chk("含流程表单", any(f["has_flow"] for f in forms))
flow_key = next((f["key"] for f in forms if f["has_flow"]), None)

r = client.get("/api/hrm/meta/emp_archive", headers=H)
chk("GET meta/emp_archive 200", r.status_code == 200, f"({r.status_code})")
meta = r.json() if r.status_code == 200 else {}
name_col = next((f["col"] for f in meta.get("fields", []) if f["label"] == "姓名"), None)
sub_col = next((s["col"] for s in meta.get("subforms", []) if s["label"] == "紧急联系人"), None)
chk("取到姓名字段列", bool(name_col))
chk("取到紧急联系人子表单", bool(sub_col))

r = client.get("/api/hrm/meta/not_exist_form", headers=H)
chk("未知表单 meta → 404", r.status_code == 404, f"({r.status_code})")

print("== 2. 建单（中文标签键 + 子表单）")
r = client.post("/api/hrm/emp_archive", headers=H, json={
    "姓名": "张三", "部门": "研发部",
    "紧急联系人": [{"紧急联系人姓名": "李四", "紧急联系人关系": "配偶", "紧急联系人电话": "13800000000"}],
})
chk("POST 建单 200", r.status_code == 200, f"({r.status_code}) {r.text[:120]}")
rid = r.json().get("id") if r.status_code == 200 else None
chk("返回 id", bool(rid))

r = client.get(f"/api/hrm/emp_archive/{rid}", headers=H)
chk("GET 单条 200", r.status_code == 200, f"({r.status_code})")
d = r.json() if r.status_code == 200 else {}
chk("姓名落库", d.get(name_col) == "张三", f"({d.get(name_col)})")
chk("子表单随主表返回", isinstance(d.get(sub_col), list) and len(d[sub_col]) == 1)
sn_val = next((v for k, v in d.items() if isinstance(v, str) and v.startswith("FR")), None)
chk("流水号自动生成", bool(sn_val), f"({sn_val})")

print("== 3. 列表 / 视图")
r = client.get("/api/hrm/emp_archive", headers=H, params={"page": 1, "size": 20})
chk("GET 列表 200", r.status_code == 200, f"({r.status_code})")
chk("列表非空", len(r.json().get("rows", [])) >= 1)

print("== 4. 更新 / 错误码")
r = client.put(f"/api/hrm/emp_archive/{rid}", headers=H, json={"姓名": "张三丰"})
chk("PUT 更新 200", r.status_code == 200, f"({r.status_code})")
r = client.get(f"/api/hrm/emp_archive/{rid}", headers=H)
chk("更新生效", r.json().get(name_col) == "张三丰")

r = client.put(f"/api/hrm/emp_archive/{rid}", headers=H, json={"压根没这字段": 1})
chk("未知字段 → 400", r.status_code == 400, f"({r.status_code})")
r = client.get("/api/hrm/emp_archive/not_exist_id", headers=H)
chk("不存在的记录 → 404", r.status_code == 404, f"({r.status_code})")

print("== 5. 审批流（含通配路由顺序回归）")
r = client.post(f"/api/hrm/{flow_key}", headers=H, json={})
chk("流程表单建单 200", r.status_code == 200, f"({r.status_code})")
fid = r.json().get("id") if r.status_code == 200 else None
r = client.post(f"/api/hrm/{flow_key}/{fid}/submit", headers=H)
chk("提交审批 200", r.status_code == 200, f"({r.status_code}) {r.text[:120]}")
iid = r.json().get("instance_id") if r.status_code == 200 else None
chk("返回流程实例 id", bool(iid))

# 关键回归：/api/hrm/flows/pending 必须不被 /api/hrm/{form_key}/{rid} 截胡
r = client.get("/api/hrm/flows/pending", headers=H)
chk("GET flows/pending 200（未被通配截胡）", r.status_code == 200, f"({r.status_code}) {r.text[:120]}")
instances = r.json().get("instances", []) if r.status_code == 200 else []
chk("待办含该实例", any(x["id"] == iid for x in instances))

r = client.post(f"/api/hrm/flows/{iid}/decide", headers=H, json={"approve": True, "note": "同意"})
chk("审批通过 200", r.status_code == 200, f"({r.status_code})")
chk("状态=approved", r.json().get("status") == "approved", f"({r.json().get('status')})")
r = client.get(f"/api/hrm/{flow_key}/{fid}", headers=H)
chk("行状态同步 approved", r.json().get("flow_status") == "approved")

print("== 6. 删除")
r = client.delete(f"/api/hrm/emp_archive/{rid}", headers=H)
chk("DELETE 200", r.status_code == 200, f"({r.status_code})")
r = client.get(f"/api/hrm/emp_archive/{rid}", headers=H)
chk("删除后 404", r.status_code == 404, f"({r.status_code})")

print(f"\n结果: PASS={PASS} FAIL={FAIL}")
try:
    os.remove(_tmp)
except OSError:
    pass
sys.exit(1 if FAIL else 0)
