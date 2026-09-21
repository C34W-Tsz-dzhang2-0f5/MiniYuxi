#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简道云《HRM人事管理系统》结构逆向 → MiniYuxi Schema 生成器。

输入：/tmp/hrm_menu.json（应用树）+ /tmp/hrm_forms/<formId>.json（每个表单的 info_access 响应）
输出：core/hrm_schema.json（MiniYuxi 可直接加载的、数据驱动的结构定义）

用法：
    python tools/gen_hrm_schema.py
（需在 14_自研MiniYuxi 目录下运行，或自行调整 INPUT/OUTPUT 路径）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
def _resolve_tmp(sub: str) -> str:
    """兼容 Git-Bash(/tmp) 与 Windows(C:\\tmp) 两种落地位置。"""
    for base in ("/tmp", "C:/tmp", "C:\\tmp"):
        p = os.path.join(base, sub)
        if os.path.exists(p):
            return p
    # 都不存在时返回首个（让报错信息可见）
    return os.path.join("/tmp", sub)


INPUT_DIR = _resolve_tmp("hrm_forms")
MENU_PATH = _resolve_tmp("hrm_menu.json")
OUTPUT = os.path.join(ROOT, "core", "hrm_schema.json")

# 49 个表单的中文名 → SQL 安全的英文表键（逆向时人工对齐，保证可读性）
KEY_MAP = {
    "员工档案": "emp_archive",
    "部门岗位基础表": "dept_position",
    "员工合同管理": "emp_contract",
    "辅助表-年月": "dim_year_month",
    "期初期末员工数量计算": "emp_count_calc",
    "考核周期": "review_cycle",
    "指标库": "kpi_library",
    "考核模板": "review_template",
    "考勤周期": "attendance_cycle",
    "假别基础表": "leave_type",
    "工作日历": "work_calendar",
    "考勤打卡": "attendance_clock",
    "个人所得税税率表": "tax_rate",
    "城市五险一金缴纳比例": "city_insurance_rate",
    "薪资项": "salary_item",
    "员工薪资结构": "emp_salary_struct",
    "员工五险一金缴纳基数": "emp_insurance_base",
    "员工专项附加扣除": "emp_special_deduction",
    "导入发起工资计算": "payroll_calc",
    "招聘需求": "recruit_demand",
    "JD 基础表": "jd_base",
    "工作地点基础表": "work_location",
    "人才库": "talent_pool",
    "offer发放": "offer_send",
    "offer跟进": "offer_follow",
    "简历推荐": "resume_recommend",
    "应用说明 💡": "app_help",
    "员工个人附件收集": "emp_attachment",
    "入职审批": "onboard_apply",
    "转正审批": "regularization_apply",
    "岗位调动审批": "transfer_apply",
    "离职申请与交接": "offboard_apply",
    "人事证明开具": "hr_cert_apply",
    "离职面谈": "offboard_interview",
    "绩效考核计划制定": "review_plan",
    "绩效结果考核": "review_result",
    "绩效面谈": "review_interview",
    "补卡申请": "repair_clock_apply",
    "请假申请": "leave_apply",
    "出差申请": "travel_apply",
    "工资条": "payslip",
    "员工工资明细": "payroll_detail",
    "简历收集及初筛": "resume_screen",
    "发起面试": "interview_apply",
    "用人单位评估": "employer_eval",
    "考勤确认": "attendance_confirm",
    "外勤打卡": "field_clock",
    "加班申请": "overtime_apply",
    "调休申请": "comp_leave_apply",
}

# 简道云 widget 类型 → (SQLite 列类型, 是否以 JSON 文本存储)
# json=True 的字段在写入时 JSON.dumps，读取时 JSON.loads
TYPE_SQL = {
    "separator": ("TEXT", False),      # 分隔符/标题，仅布局，不建列
    "text": ("TEXT", False),
    "textarea": ("TEXT", False),
    "number": ("REAL", False),
    "sn": ("TEXT", False),             # 流水号
    "combo": ("TEXT", False),          # 下拉单选（值=选项文本）
    "radiogroup": ("TEXT", False),     # 单选组（简道云实际类型名）
    "combocheck": ("TEXT", True),      # 下拉多选 → JSON 数组
    "checkbox": ("TEXT", True),        # 多选 → JSON 数组（兜底）
    "radio": ("TEXT", False),          # 单选（兜底）
    "user": ("TEXT", True),            # 成员 → JSON 数组[{id,name}]
    "usergroup": ("TEXT", True),       # 成员组 → JSON 数组
    "dept": ("TEXT", True),            # 部门 → JSON 数组[{id,name}]
    "datetime": ("TEXT", False),       # ISO 文本
    "date": ("TEXT", False),
    "time": ("TEXT", False),
    "address": ("TEXT", True),         # 地址 → JSON
    "upload": ("TEXT", True),          # 附件 → JSON 数组
    "image": ("TEXT", True),           # 图片 → JSON 数组
    "signature": ("TEXT", True),       # 签名 → JSON（图片/笔迹）
    "subform": ("TEXT", False),        # 子表单 → 独立子表（此处不建列）
    "linkquery": ("TEXT", True),       # 关联查询 → JSON 引用
    "linkfield": ("TEXT", False),      # 关联字段 → 外键 id
    "score": ("REAL", False),          # 评分
    "money": ("REAL", False),          # 金额
    "location": ("TEXT", True),        # 定位 → JSON
    "phone": ("TEXT", False),
    "email": ("TEXT", False),
    "switch": ("INTEGER", False),      # 开关 0/1
    "barcode": ("TEXT", False),
}
DEFAULT_TYPE = ("TEXT", False)


def clean_col(widget_name: str) -> str:
    """widgetName（_widget_xxx）→ SQL 安全列名 widget_xxx。"""
    return widget_name.replace("_widget_", "w_")


def extract_options(widget: dict):
    """抽取 combo 的静态选项（数据字典）。返回 [{value,label}] 或 None。"""
    opts = widget.get("options")
    if not opts:
        return None
    out = []
    try:
        if isinstance(opts, list):
            for o in opts:
                if isinstance(o, dict):
                    out.append({"value": o.get("value", o.get("text", "")), "label": o.get("label", o.get("text", ""))})
                else:
                    out.append({"value": str(o), "label": str(o)})
        elif isinstance(opts, dict):
            for k, v in opts.items():
                out.append({"value": k, "label": v if isinstance(v, str) else str(v)})
    except Exception:
        return None
    return out or None


def extract_async_source(widget: dict):
    """combo 的异步数据源（从另一张表单的字段取选项）。"""
    async_cfg = widget.get("async")
    if isinstance(async_cfg, dict) and isinstance(async_cfg.get("data"), dict):
        d = async_cfg["data"]
        return {"form_id": d.get("formId"), "field": d.get("field")}
    return None


def extract_field(item: dict) -> dict:
    """从 entry.content.items[i] 抽取字段定义。"""
    w = item.get("widget", {}) or {}
    t = w.get("type", "text")
    fld = {
        "label": item.get("label", ""),
        "col": clean_col(w.get("widgetName", "")),
        "widget": w.get("widgetName", ""),
        "type": t,
        "required": w.get("allowBlank", True) is False,
    }
    if t == "combo":
        fld["options"] = extract_options(w)
        fld["async_source"] = extract_async_source(w)
    if t in ("subform",):
        nested = w.get("items", []) or []
        fld["subfields"] = [extract_field(s) for s in nested]
    if t in ("linkquery", "linkfield"):
        fld["link"] = {
            "link_filter": w.get("linkFilter"),
            "link_fields": w.get("linkFields"),
            "data": w.get("data"),
        }
    if w.get("rules"):
        fld["rules"] = w["rules"]          # 如 sn 流水号：fixedChars + incNumber
    if "defaultValue" in w:
        fld["default"] = w["defaultValue"]
    return fld


def extract_auth_groups(raw: dict) -> list:
    """权限组：位于 info_access 响应顶层 raw.authGroups（不在 entry 下）。"""
    groups = raw.get("authGroups") or []
    out = []
    for g in groups:
        perms = g.get("dataPerms") or {}
        out.append({
            "name": g.get("name", ""),
            "data_perms": {k: bool(v) for k, v in perms.items()},
            "opt_auth": g.get("optAuth"),
        })
    return out


def extract_views(raw: dict) -> list:
    """视图：位于响应顶层 raw.views（列表/看板/筛选/排序）。"""
    views = raw.get("views") or []
    out = []
    for v in views:
        out.append({
            "name": v.get("name", ""),
            "type": v.get("type", "list"),
            "filter": v.get("filter"),
            "sort": v.get("sort"),
            "kanban": v.get("kanban"),
        })
    return out


def _extract_relationships(raw: dict) -> list:
    """跨表单关联（用于还原 linkquery/linkfield 的外键指向）。"""
    rels = raw.get("relationships") or []
    out = []
    for r in rels if isinstance(rels, list) else []:
        if isinstance(r, dict):
            out.append({k: r.get(k) for k in ("name", "formId", "entryId", "type", "widgetName") if k in r})
    return out


def main():
    if not os.path.exists(MENU_PATH):
        print("缺少菜单文件:", MENU_PATH, file=sys.stderr)
        sys.exit(1)
    menu = json.load(open(MENU_PATH, encoding="utf-8"))
    emap = menu.get("entryMap", {})

    forms = []
    missing = []
    for fid, v in emap.items():
        if v.get("type") != "form":
            continue
        name = v.get("name", "")
        key = KEY_MAP.get(name)
        if not key:
            # 兜底：用 formId 后缀
            key = "form_" + fid[-10:]
            print(f"⚠ 未配置英文名映射：{name} → {key}", file=sys.stderr)
        path = os.path.join(INPUT_DIR, fid + ".json")
        if not os.path.exists(path):
            missing.append((name, fid))
            continue
        try:
            raw = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            missing.append((name, fid))
            print(f"⚠ 解析失败 {name}: {e}", file=sys.stderr)
            continue
        entry = raw.get("entry") or {}
        items = (entry.get("content") or {}).get("items") or []
        fields = [extract_field(it) for it in items]
        subforms = [f for f in fields if f["type"] == "subform"]
        # 去掉 separator（不建列）但保留用于布局还原
        # 注意（逆向踩坑）：
        # - views / authGroups 在响应「顶层」，不在 entry 下，从 entry 取会得到空数组；
        # - 顶层 flow 只是 UI 开关（allowSave / hasDeptManagerChain），不代表有审批流；
        #   审批流标志只能取 menu.entryMap[].hasFlow 或 entry.hasFlow。
        rec = {
            "key": key,
            "id": fid,
            "name": name,
            "has_flow": bool(v.get("hasFlow")) or bool(entry.get("hasFlow")),
            "comment": entry.get("comment"),
            "fields": fields,
            "subforms": [{"col": s["col"], "widget": s["widget"], "label": s["label"],
                          "subfields": s.get("subfields", [])} for s in subforms],
            "auth_groups": extract_auth_groups(raw),
            "views": extract_views(raw),
            "buttons": raw.get("buttons") or [],
            "relationships": _extract_relationships(raw),
            "flow": raw.get("flow") if entry.get("hasFlow") else None,
        }
        forms.append(rec)

    forms.sort(key=lambda f: f["key"])
    schema = {
        "source": "简道云《HRM人事管理系统》 appId=6aaf4ffd3e5274a5665d4811",
        "generated_by": "tools/gen_hrm_schema.py",
        "form_count": len(forms),
        "type_sql": {k: {"sql": v[0], "json": v[1]} for k, v in TYPE_SQL.items()},
        "forms": forms,
    }
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    json.dump(schema, open(OUTPUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ 生成 {OUTPUT}")
    print(f"   表单数: {len(forms)} / 缺失: {len(missing)}")
    if missing:
        for n, i in missing:
            print(f"   缺失: {n} ({i})")
    # 统计类型分布
    hist = {}
    for f in forms:
        for fld in f["fields"]:
            hist[fld["type"]] = hist.get(fld["type"], 0) + 1
    print("   字段类型分布:", json.dumps(hist, ensure_ascii=False))


if __name__ == "__main__":
    main()
