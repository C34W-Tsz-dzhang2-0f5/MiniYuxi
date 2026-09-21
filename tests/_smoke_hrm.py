#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HRM 迁移引擎冒烟测试：在临时库上建全部表并跑通 CRUD / 子表单 / 审批流。

用法（项目根目录）：
    MINIYUXI_DB=<temp>.db python tests/_smoke_hrm.py
"""
import os
import sys
import tempfile

# 用临时库，避免污染开发库
_tmp = os.path.join(tempfile.gettempdir(), "hrm_smoke.db")
if os.path.exists(_tmp):
    os.remove(_tmp)
os.environ["MINIYUXI_DB"] = _tmp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.hrm as hrm
from core import auth

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name} {extra}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def main():
    print("== HRM 引擎冒烟测试 ==")
    hrm.init()
    forms = hrm.list_forms()
    check(f"表单数=49 (实际 {len(forms)})", len(forms) == 49)
    check("员工档案存在", any(f["key"] == "emp_archive" for f in forms))
    check("入职审批为流程表单", any(f["key"] == "onboard_apply" and f["has_flow"] for f in forms))

    # 用 admin 身份
    p = auth.Principal("default", "admin", "admin")

    # --- 员工档案：含子表单(紧急联系人) + json字段(user/dept/address) ---
    meta = hrm.form_meta("emp_archive")
    cols = {f["col"]: f for f in meta["fields"]}
    # 找几个真实列
    name_col = next(c for c, f in cols.items() if f["label"] == "姓名")
    dept_col = next(c for c, f in cols.items() if f["label"] == "部门")
    user_col = next(c for c, f in cols.items() if f["label"] == "员工成员单选")
    addr_col = next(c for c, f in cols.items() if f["label"] == "籍贯")
    sn_col = next(c for c, f in cols.items() if f["label"] == "工号")
    sub = next(s for s in meta["subforms"] if s["label"] == "紧急联系人")

    rec = hrm.row_create("emp_archive", {
        name_col: "张三",
        dept_col: "研发部",
        user_col: [{"id": "u1", "name": "张三"}],
        addr_col: {"province": "广东", "city": "深圳", "district": "南山", "detail": "科技园"},
        sub["col"]: [{"紧急联系人姓名": "李四", "紧急联系人关系": "配偶", "紧急联系人电话": "13800000000"}],
    }, p)
    check("员工档案创建返回 id", bool(rec.get("id")))
    rid = rec["id"]

    got = hrm.row_get("emp_archive", rid, p)
    check("姓名写入正确", got.get(name_col) == "张三")
    check("user 字段 JSON 还原", got.get(user_col) == [{"id": "u1", "name": "张三"}])
    check("address 字段 JSON 还原", got.get(addr_col) == {"province": "广东", "city": "深圳", "district": "南山", "detail": "科技园"})
    check("子表单随主表返回", isinstance(got.get(sub["col"]), list) and len(got[sub["col"]]) == 1)
    check("工号自动生成(FR开头)", str(got.get(sn_col, "")).startswith("FR"))

    upd = hrm.row_update("emp_archive", rid, {name_col: "张三丰"}, p)
    check("更新成功", upd.get("updated") is True)
    check("更新生效", hrm.row_get("emp_archive", rid, p).get(name_col) == "张三丰")

    lst = hrm.row_list("emp_archive", p)
    check("列表含 1 条", len(lst) == 1)

    # --- 中文标签键建单（简道云导出数据的真实形态）---
    rec2 = hrm.row_create("emp_archive", {
        "姓名": "李四",
        "部门": "市场部",
        "紧急联系人": [{"紧急联系人姓名": "王五", "紧急联系人关系": "父子", "紧急联系人电话": "13900000000"}],
    }, p)
    g2 = hrm.row_get("emp_archive", rec2["id"], p)
    check("标签键建单→姓名落库", g2.get(name_col) == "李四")
    check("标签键子表单落库", g2.get(sub["col"])[0].get(
        next(s["col"] for s in sub["subfields"] if s["label"] == "紧急联系人姓名")) == "王五")
    check("未知字段严格报错", _raises(lambda: hrm.row_create("emp_archive", {"不存在的字段": 1}, p)))
    hrm.row_delete("emp_archive", rec2["id"], p)

    # --- 权限矩阵（复刻简道云 authGroups dataPerms）---
    class _P:
        def __init__(self, role):
            self.tenant_id, self.username, self.role = "default", role, role

    g_add = _P("仅添加数据")      # 简道云权限组：create=True / read=False
    g_admin = _P("admin")
    check("权限组[仅添加数据] 可读=False", hrm.check_perm("emp_archive", g_add, "read") is False)
    check("权限组[仅添加数据] 可建=True", hrm.check_perm("emp_archive", g_add, "create") is True)
    check("admin 全放行", hrm.check_perm("emp_archive", g_admin, "delete") is True)
    check("未映射角色沿用粗粒度权限", hrm.check_perm("emp_archive", _P("editor"), "read") is True)
    mx = hrm.perm_matrix("emp_archive")
    check("权限矩阵导出 4 组", len(mx) == 4, f"(实际 {len(mx)})")

    # --- 流程表单：入职审批 submit → decide ---
    fm = hrm.form_meta("onboard_apply")
    fcols = {f["col"]: f for f in fm["fields"]}
    fn = next(c for c, f in fcols.items() if f["label"] == "员工姓名") if any(f["label"] == "员工姓名" for f in fcols.values()) else next(iter(fcols))
    a = hrm.row_create("onboard_apply", {fn: "王五"}, p)
    sub2 = hrm.flow_submit("onboard_apply", a["id"], p)
    check("流程提交生成实例", bool(sub2.get("instance_id")))
    check("提交后状态=pending", hrm.row_get("onboard_apply", a["id"], p).get("flow_status") == "pending")
    pend = hrm.flow_list_pending("default")
    check("待审批列表含该实例", any(x["id"] == sub2["instance_id"] for x in pend))
    dec = hrm.flow_decide(sub2["instance_id"], True, "admin", "同意")
    check("审批后状态=approved", dec.get("status") == "approved")
    check("行状态同步=approved", hrm.row_get("onboard_apply", a["id"], p).get("flow_status") == "approved")

    # --- 删除 ---
    d = hrm.row_delete("emp_archive", rid, p)
    check("删除成功", d.get("deleted") is True)
    check("删除后查不到", hrm.row_get("emp_archive", rid, p) is None)

    print(f"\n结果: PASS={PASS} FAIL={FAIL}")
    try:
        os.remove(_tmp)
    except OSError:
        pass
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
