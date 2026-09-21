#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简道云《HRM人事管理系统》数据迁移导入器。

把简道云导出的数据灌进 miniyuxi 的 hrm_<key> 表。

支持的输入（--dir 目录或 --file 单文件）：
  1. CSV / Excel 导出的 .csv：表头为简道云「字段标题」。
     - 主表字段：表头直接是标题，如「姓名」「部门」
     - 子表单字段：表头形如「紧急联系人.紧急联系人姓名」或「紧急联系人[0].姓名」
  2. JSON（.json）：数组，每项即为一条记录，子表单直接内嵌数组：
     [{"姓名":"张三","紧急联系人":[{"紧急联系人姓名":"李四"}]}, ...]

文件命名：<form_key>.csv（如 emp_archive.csv）或 <表单中文名>.csv（如 员工档案.csv）。
可用 --form 显式指定表单（此时 --file 只处理一个文件）。

用法：
    python tools/import_hrm_data.py --dir ./jdy_export --tenant default --user admin
    python tools/import_hrm_data.py --dir ./jdy_export --dry-run        # 只校验不落库
    python tools/import_hrm_data.py --file ./员工档案.csv --form emp_archive

注意：导入前会按表单 schema 校验字段；未知字段默认报错（--on-unknown skip 可跳过）。
"""
import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.hrm as hrm  # noqa: E402
from core import auth  # noqa: E402

SUB_HEAD_RE = re.compile(r"^(?P<sub>[^.\[]+)\s*(?:\[\d+\])?\s*\.\s*(?P<field>.+)$")


class _P:
    """轻量 principal（不依赖 HTTP 上下文）。"""

    def __init__(self, tenant_id, username):
        self.tenant_id = tenant_id
        self.username = username


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        return list(rdr), (rdr.fieldnames or [])


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):  # 兼容 {"data":[...]} 包装
        for k in ("data", "rows", "list", "records"):
            if isinstance(data.get(k), list):
                return data[k]
        return [data]
    return data if isinstance(data, list) else []


def _split_row(fm, row):
    """把扁平 CSV 行拆成 {主字段} + {子表单: [ {...} ]}。"""
    main, subs = {}, {}
    sub_labels = {sf.get("label"): sf["col"] for sf in fm["subforms"] if sf.get("label")}
    sub_cols = {sf["col"] for sf in fm["subforms"]}
    for k, v in row.items():
        if k is None:
            continue
        key = k.strip()
        if v is None or v == "":
            continue
        m = SUB_HEAD_RE.match(key)
        if m and (m.group("sub") in sub_labels or m.group("sub") in sub_cols):
            sname = m.group("sub")
            scol = sub_labels.get(sname, sname)
            subs.setdefault(scol, [{}])[0][m.group("field").strip()] = v
        else:
            main[key] = v
    return main, subs


def import_file(path, form_key, principal, dry_run=False, on_unknown="fail", conn=None):
    fm = hrm.form_meta(form_key)
    if not fm:
        return {"file": path, "form": form_key, "error": "未知表单", "ok": 0, "fail": 0}

    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        rows = _read_json(path)
        prepared = [(r, {}) for r in rows if isinstance(r, dict)]
    else:
        raw, _ = _read_csv(path)
        prepared = [_split_row(fm, r) for r in raw]

    ok = fail = 0
    errors = []
    for i, (main, subs) in enumerate(prepared, 1):
        data = dict(main)
        data.update(subs)
        if not data:
            continue
        try:
            if dry_run:
                # 仅做字段解析校验，不落库
                unknown = [k for k in data if hrm._resolve_key(
                    hrm._FORM_BY_KEY[form_key], k)[0] == "unknown"]
                if unknown:
                    if on_unknown == "fail":
                        raise ValueError(f"未知字段: {unknown}")
                    for u in unknown:
                        data.pop(u, None)
            else:
                hrm.row_create(form_key, data, principal,
                               strict=(on_unknown == "fail"), conn=conn)
            ok += 1
        except Exception as e:
            fail += 1
            if len(errors) < 5:
                errors.append(f"第{i}行: {e}")
    return {"file": os.path.basename(path), "form": form_key, "name": fm["name"],
            "ok": ok, "fail": fail, "errors": errors}


def main():
    ap = argparse.ArgumentParser(description="简道云 HRM 数据导入 miniyuxi")
    ap.add_argument("--dir", help="导出目录（内含 <表单名>.csv / .json）")
    ap.add_argument("--file", help="单个导出文件")
    ap.add_argument("--form", help="显式指定表单 key（配合 --file）")
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--user", default="migration")
    ap.add_argument("--dry-run", action="store_true", help="只校验不落库")
    ap.add_argument("--on-unknown", choices=["fail", "skip"], default="fail")
    args = ap.parse_args()

    if not args.dir and not args.file:
        ap.error("需要 --dir 或 --file")

    hrm.init()
    forms = hrm.list_forms()
    by_key = {f["key"]: f for f in forms}
    by_name = {f["name"]: f for f in forms}
    principal = _P(args.tenant, args.user)

    targets = []
    if args.file:
        if not args.form:
            stem = os.path.splitext(os.path.basename(args.file))[0]
            fm = by_name.get(stem) or by_key.get(stem)
            if not fm:
                print(f"无法从文件名推断表单：{stem}，请用 --form 指定")
                sys.exit(2)
            args.form = fm["key"]
        targets.append((args.file, args.form))
    else:
        for fn in sorted(os.listdir(args.dir)):
            if not fn.lower().endswith((".csv", ".json")):
                continue
            stem = os.path.splitext(fn)[0]
            fm = by_key.get(stem) or by_name.get(stem)
            if not fm:
                print(f"  跳过（未匹配到表单）：{fn}")
                continue
            targets.append((os.path.join(args.dir, fn), fm["key"]))

    total_ok = total_fail = 0
    print(f"== 导入 {'[DRY-RUN] ' if args.dry_run else ''}共 {len(targets)} 个文件 ==")
    for path, fk in targets:
        r = import_file(path, fk, principal, args.dry_run, args.on_unknown)
        total_ok += r.get("ok", 0)
        total_fail += r.get("fail", 0)
        flag = "✗" if r.get("error") or r.get("fail") else "✓"
        print(f"  {flag} {r.get('name', fk):<14} ok={r.get('ok', 0)} fail={r.get('fail', 0)}"
              + (f"  {r['error']}" if r.get("error") else ""))
        for e in r.get("errors", []):
            print(f"      - {e}")
    print(f"\n合计：成功 {total_ok} 行，失败 {total_fail} 行")
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
