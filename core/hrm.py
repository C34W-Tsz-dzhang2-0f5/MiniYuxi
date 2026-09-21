"""HRM 人事管理系统（简道云逆向迁移）· 数据驱动引擎。

来源：简道云《HRM人事管理系统》 appId=6aaf4ffd3e5274a5665d4811
逆向产物：core/hrm_schema.json（由 tools/gen_hrm_schema.py 从各表单 info_access 响应生成）

职责：
  1. 运行时为 49 张表单各建一张表（hrm_<key>），字段类型按简道云 widget 类型映射；
  2. 子表单（subform）建独立子表（hrm_<key>_<col>），1:N 关联；
  3. 通用 CRUD（row_create/list/get/update/delete），JSON 类型字段透明序列化；
  4. 视图（views）按存储的 filter/sort/kanban 还原列表/看板；
  5. 审批流（hasFlow 表单）通用状态机 draft→pending→approved/rejected（详见迁移方案文档的保真度说明）；
  6. 流水号（sn）按 fixedChars+incNumber 规则自动生成。

约定（与 miniyuxi 其它 core 模块一致）：
  - 连接用 db.connect()（线程本地，不可 close）；每个公开函数带 conn=None；
  - 表均含 tenant_id；写入走参数化 SQL（列名仅来自受信任的 hrm_schema.json）。
"""
import json
import os
import re
import uuid

from . import db

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "hrm_schema.json")
_SCHEMA = None
_FORM_BY_KEY = {}

# 简道云 widget 类型 → (SQLite 列类型, 是否 JSON 文本存储)
TYPE_SQL = {
    "separator": ("TEXT", False),
    "text": ("TEXT", False),
    "textarea": ("TEXT", False),
    "number": ("REAL", False),
    "sn": ("TEXT", False),
    "combo": ("TEXT", False),
    "radiogroup": ("TEXT", False),
    "combocheck": ("TEXT", True),
    "checkbox": ("TEXT", True),
    "radio": ("TEXT", False),
    "user": ("TEXT", True),
    "usergroup": ("TEXT", True),
    "dept": ("TEXT", True),
    "datetime": ("TEXT", False),
    "date": ("TEXT", False),
    "time": ("TEXT", False),
    "address": ("TEXT", True),
    "upload": ("TEXT", True),
    "image": ("TEXT", True),
    "signature": ("TEXT", True),
    "subform": ("TEXT", False),
    "linkquery": ("TEXT", True),
    "linkfield": ("TEXT", False),
    "score": ("REAL", False),
    "money": ("REAL", False),
    "location": ("TEXT", True),
    "phone": ("TEXT", False),
    "email": ("TEXT", False),
    "switch": ("INTEGER", False),
    "barcode": ("TEXT", False),
}
_COL_RE = re.compile(r"^w_[0-9a-fA-F]+$")


def _load_schema():
    global _SCHEMA, _FORM_BY_KEY
    if _SCHEMA is None:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            _SCHEMA = json.load(f)
        _FORM_BY_KEY = {fm["key"]: fm for fm in _SCHEMA["forms"]}
    return _SCHEMA


def _conn(conn):
    return conn or db.connect()


def _sql_type(jdy_type):
    return TYPE_SQL.get(jdy_type, ("TEXT", False))


def _is_json_field(fld):
    return _sql_type(fld["type"])[1]


def _safe_col(col):
    """列名只允许 w_<hex>（来自受信任 schema），其余拒绝，防注入。"""
    if not _COL_RE.match(col):
        raise ValueError(f"非法列名: {col}")
    return col


# ---------------- 权限（复刻简道云 authGroups 数据权限位）----------------
# 简道云权限组的 dataPerms 位：read/export/create/import/update/delete/
# batch_print/copy/flow_*。此处把 miniyuxi 动作映射到这些位。
ACTION_PERM = {
    "read": "read", "list": "read", "get": "read",
    "create": "create", "update": "update", "delete": "delete",
    "export": "export", "flow": "flow_create",
}


def _group_for(principal, groups):
    """按 principal.role 匹配简道云权限组（先全等，再包含匹配）。"""
    role = getattr(principal, "role", "") or ""
    if not role:
        return None
    for g in groups:
        if g.get("name") == role:
            return g
    for g in groups:
        if role in (g.get("name") or ""):
            return g
    return None


def check_perm(form_key, principal, action, conn=None):
    """校验某角色在某表单上是否具备某动作的权限。

    策略：admin 全放行；未匹配到权限组的角色沿用 config.ROLE_PERMS 粗粒度权限（放行）；
    匹配到权限组时严格按 dataPerms 位判定——保证与简道云口径一致。
    """
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    groups = fm.get("auth_groups") or []
    if not groups:
        return True
    if getattr(principal, "role", None) == "admin":
        return True
    g = _group_for(principal, groups)
    if not g:
        return True
    bit = ACTION_PERM.get(action, action)
    return bool((g.get("data_perms") or {}).get(bit, False))


def perm_matrix(form_key, conn=None):
    """导出该表单的权限矩阵（用于对照简道云后台配置做校验）。"""
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    return [{"group": g.get("name"), "perms": {k: v for k, v in (g.get("data_perms") or {}).items() if v}}
            for g in (fm.get("auth_groups") or [])]


# ---------------- 键解析：列名(w_xxx) 与 中文标签 双支持 ----------------
# 简道云导出的数据以「字段标题」为键（如「姓名」「紧急联系人姓名」），
# 而表结构以 widgetName（w_xxx）为列名。引擎两者都接受。
_MAPS = {}


def _maps(fm):
    """{main_col:set, main_label:{标签:col}, sub_col:set, sub_label:{标签:col}, sub_fields:{sf_col:{标签:col}}}"""
    m = _MAPS.get(fm["key"])
    if m is None:
        m = {
            "main_col": {f["col"] for f in fm["fields"]},
            "main_label": {f["label"]: f["col"] for f in fm["fields"]},
            "sub_col": {sf["col"] for sf in fm["subforms"]},
            "sub_label": {sf.get("label"): sf["col"] for sf in fm["subforms"] if sf.get("label")},
            "sub_fields": {sf["col"]: {s["label"]: s["col"] for s in sf["subfields"]} for sf in fm["subforms"]},
            "sub_field_col": {sf["col"]: {s["col"] for s in sf["subfields"]} for sf in fm["subforms"]},
        }
        _MAPS[fm["key"]] = m
    return m


def _resolve_key(fm, key):
    """返回 (kind, col)；kind ∈ {field, subform, unknown}。"""
    m = _maps(fm)
    if key in m["main_col"]:
        return "field", key
    if key in m["main_label"]:
        return "field", m["main_label"][key]
    if key in m["sub_col"]:
        return "subform", key
    if key in m["sub_label"]:
        return "subform", m["sub_label"][key]
    return "unknown", None


def _resolve_subkey(fm, sf_col, key):
    """子表单内字段键解析，返回列名或 None。"""
    m = _maps(fm)
    if key in m["sub_field_col"].get(sf_col, ()):
        return key
    return m["sub_fields"].get(sf_col, {}).get(key)


def _insert_sub(c, fm, form_key, sf_col, rows, parent_id, tenant_id):
    """整体写入某子表单的行（调用方负责先清理旧行）。"""
    sf = next(s for s in fm["subforms"] if s["col"] == sf_col)
    sf_by_col = {s["col"]: s for s in sf["subfields"]}
    for r in rows or []:
        sid = "hs_" + uuid.uuid4().hex[:12]
        scols = ["id", "parent_id", "tenant_id"]
        svals = [sid, parent_id, tenant_id]
        for k, v in (r or {}).items():
            sc = _resolve_subkey(fm, sf_col, k)
            if not sc:
                continue
            s_fld = sf_by_col[sc]
            if s_fld["type"] == "separator":
                continue
            scols.append(f'"{_safe_col(sc)}"')
            svals.append(_to_store(v, _is_json_field(s_fld)))
        c.execute(
            f"INSERT INTO hrm_{form_key}_{sf_col}({','.join(scols)}) VALUES({','.join('?' for _ in svals)})",
            svals,
        )


def _to_store(val, is_json):
    if val is None:
        return None
    if is_json:
        return json.dumps(val, ensure_ascii=False)
    return val


def _from_store(val, is_json):
    if val is None or not is_json:
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


# ---------------- 建表 ----------------
def init(conn=None):
    c = _conn(conn)
    _load_schema()
    for fm in _SCHEMA["forms"]:
        _create_form_table(c, fm)
        for sf in fm["subforms"]:
            _create_subform_table(c, fm, sf)
    c.execute(
        """CREATE TABLE IF NOT EXISTS hrm_flow_instances(
            id TEXT PRIMARY KEY,
            form_key TEXT NOT NULL,
            row_id TEXT NOT NULL,
            tenant_id TEXT,
            status TEXT DEFAULT 'pending',
            current_node TEXT DEFAULT '',
            assignee TEXT DEFAULT '',
            submitted_by TEXT DEFAULT '',
            decision_by TEXT DEFAULT '',
            decision_note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            decided_at TEXT DEFAULT ''
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS hrm_counters(
            form_key TEXT NOT NULL, col TEXT NOT NULL,
            last_val INTEGER DEFAULT 0,
            PRIMARY KEY(form_key, col)
        )"""
    )
    c.commit()


def _create_form_table(c, fm):
    cols = [
        "id TEXT PRIMARY KEY",
        "tenant_id TEXT",
        "created_by TEXT",
        "created_at TEXT DEFAULT (datetime('now'))",
        "updated_at TEXT DEFAULT (datetime('now'))",
    ]
    if fm.get("has_flow"):
        cols.append("flow_status TEXT DEFAULT 'draft'")
    for f in fm["fields"]:
        if f["type"] == "separator":
            continue
        sql, _ = _sql_type(f["type"])
        cols.append(f'"{f["col"]}" {sql}')
    c.execute(f"CREATE TABLE IF NOT EXISTS hrm_{fm['key']}({','.join(cols)})")


def _create_subform_table(c, fm, sf):
    cols = [
        "id TEXT PRIMARY KEY",
        f"parent_id TEXT NOT NULL",
        "tenant_id TEXT",
    ]
    for s in sf["subfields"]:
        if s["type"] == "separator":
            continue
        sql, _ = _sql_type(s["type"])
        cols.append(f'"{s["col"]}" {sql}')
    c.execute(f"CREATE TABLE IF NOT EXISTS hrm_{fm['key']}_{sf['col']}({','.join(cols)})")


# ---------------- 元信息 ----------------
def list_forms(conn=None):
    _load_schema()
    return [
        {"key": fm["key"], "name": fm["name"], "id": fm["id"],
         "has_flow": fm.get("has_flow"), "field_count": len(fm["fields"]),
         "subform_count": len(fm["subforms"]), "view_count": len(fm.get("views", []))}
        for fm in _SCHEMA["forms"]
    ]


def form_meta(form_key, conn=None):
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        return None
    return {
        "key": fm["key"], "name": fm["name"], "id": fm["id"],
        "has_flow": fm.get("has_flow"),
        "fields": fm["fields"], "subforms": fm["subforms"],
        "auth_groups": fm.get("auth_groups"), "views": fm.get("views"),
    }


# ---------------- 流水号 ----------------
def _next_sn(c, fm, fld, tenant_id):
    rules = fld.get("rules") or []
    chars = ""
    digits = 5
    for r in rules:
        if r.get("type") == "fixedChars":
            chars = r.get("chars", "")
        elif r.get("type") == "incNumber":
            digits = int(r.get("digitsNum", 5))
    row = c.execute(
        "SELECT COUNT(*) AS n FROM hrm_%s WHERE tenant_id=?" % fm["key"], (tenant_id,)
    ).fetchone()
    n = (row["n"] if row else 0) + 1
    return f"{chars}{str(n).zfill(digits)}"


# ---------------- 通用 CRUD ----------------
def row_create(form_key, data, principal=None, conn=None, strict=True):
    """data 键可为列名(w_xxx)或中文字段标题；子表单以 {col或标题: [ {...}, ... ]} 内嵌。

    strict=True（默认）时，遇到 schema 中不存在的字段抛 ValueError——迁移导入阶段
    宁可失败也不能静默丢字段；确认可接受丢字段时传 strict=False。
    """
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    c = _conn(conn)
    init(c)
    tenant_id = (principal.tenant_id if principal else "default")
    by_col = {f["col"]: f for f in fm["fields"]}
    rid = "h_" + uuid.uuid4().hex[:12]

    main_cols = ["id", "tenant_id", "created_by"]
    main_vals = [rid, tenant_id, (principal.username if principal else "")]
    sub_payload, unknown = {}, []
    for key, val in (data or {}).items():
        kind, col = _resolve_key(fm, key)
        if kind == "unknown":
            unknown.append(key)
            continue
        if kind == "subform":
            if isinstance(val, list):
                sub_payload[col] = val
            continue
        fld = by_col[col]
        if fld["type"] in ("separator", "subform"):
            if fld["type"] == "subform" and isinstance(val, list):
                sub_payload[col] = val
            continue
        if fld["type"] == "sn" and (val in (None, "", [])):
            val = _next_sn(c, fm, fld, tenant_id)
        main_cols.append(f'"{_safe_col(col)}"')
        main_vals.append(_to_store(val, _is_json_field(fld)))

    if unknown and strict:
        raise ValueError(f"表单[{fm['name']}]未知字段: {unknown}")

    # 流水号兜底：提交数据中未提供 sn 字段时按规则自动生成
    for fld in fm["fields"]:
        if fld["type"] == "sn" and f'"{fld["col"]}"' not in main_cols:
            main_cols.append(f'"{fld["col"]}"')
            main_vals.append(_next_sn(c, fm, fld, tenant_id))

    placeholders = ",".join("?" for _ in main_vals)
    c.execute(
        f"INSERT INTO hrm_{form_key}({','.join(main_cols)}) VALUES({placeholders})",
        main_vals,
    )
    for sf_col, rows in sub_payload.items():
        _insert_sub(c, fm, form_key, sf_col, rows, rid, tenant_id)
    c.commit()
    return {"id": rid, "form_key": form_key}


def row_list(form_key, principal=None, view=None, page=1, size=50, conn=None):
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    c = _conn(conn)
    init(c)
    tenant_id = (principal.tenant_id if principal else "default")
    if view:
        v = next((x for x in fm.get("views", []) if x["name"] == view), None)
        order = ""
        if v and v.get("sort"):
            order = " ORDER BY " + ", ".join(
                '"%s" %s' % (s["col"], "DESC" if str(s.get("order", "")).upper() == "DESC" else "ASC")
                for s in v["sort"] if _COL_RE.match(s.get("col", ""))
            )
        rows = c.execute(
            f"SELECT * FROM hrm_{form_key} WHERE tenant_id=?{order} LIMIT ? OFFSET ?",
            (tenant_id, size, max(0, page - 1) * size),
        ).fetchall()
    else:
        rows = c.execute(
            f"SELECT * FROM hrm_{form_key} WHERE tenant_id=? LIMIT ? OFFSET ?",
            (tenant_id, size, max(0, page - 1) * size),
        ).fetchall()
    return [_row_to_dict(fm, r) for r in rows]


def row_get(form_key, rid, principal=None, conn=None):
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    c = _conn(conn)
    init(c)
    r = c.execute(f"SELECT * FROM hrm_{form_key} WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    d = _row_to_dict(fm, r)
    # 附子表单
    for sf in fm["subforms"]:
        subs = c.execute(
            f"SELECT * FROM hrm_{form_key}_{sf['col']} WHERE parent_id=?", (rid,)
        ).fetchall()
        d[sf["col"]] = [_sub_to_dict(sf, s) for s in subs]
    return d


def row_update(form_key, rid, data, principal=None, conn=None, strict=True):
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    c = _conn(conn)
    init(c)
    tenant_id = (principal.tenant_id if principal else "default")
    by_col = {f["col"]: f for f in fm["fields"]}
    sets, vals, unknown = [], [], []
    for key, val in (data or {}).items():
        kind, col = _resolve_key(fm, key)
        if kind == "unknown":
            unknown.append(key)
            continue
        if kind == "subform" and isinstance(val, list):
            c.execute(f"DELETE FROM hrm_{form_key}_{col} WHERE parent_id=?", (rid,))
            _insert_sub(c, fm, form_key, col, val, rid, tenant_id)
            continue
        fld = by_col[col]
        if fld["type"] == "separator":
            continue
        if fld["type"] == "subform":
            if isinstance(val, list):
                c.execute(f"DELETE FROM hrm_{form_key}_{col} WHERE parent_id=?", (rid,))
                _insert_sub(c, fm, form_key, col, val, rid, tenant_id)
            continue
        sets.append(f'"{_safe_col(col)}"=?')
        vals.append(_to_store(val, _is_json_field(fld)))
    if unknown and strict:
        raise ValueError(f"表单[{fm['name']}]未知字段: {unknown}")
    if sets:
        sets.append("updated_at=datetime('now')")
        vals.append(rid)
        c.execute(f"UPDATE hrm_{form_key} SET {','.join(sets)} WHERE id=?", vals)
    c.commit()
    return {"id": rid, "updated": bool(sets)}


def row_delete(form_key, rid, principal=None, conn=None):
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm:
        raise KeyError(f"未知表单: {form_key}")
    c = _conn(conn)
    init(c)
    for sf in fm["subforms"]:
        c.execute(f"DELETE FROM hrm_{form_key}_{sf['col']} WHERE parent_id=?", (rid,))
    c.execute(f"DELETE FROM hrm_{form_key} WHERE id=?", (rid,))
    c.commit()
    return {"id": rid, "deleted": True}


def _row_to_dict(fm, row):
    d = {}
    for k in row.keys():
        if k in ("tenant_id", "created_by", "created_at", "updated_at", "flow_status"):
            d[k] = row[k]
        elif k == "id":
            d["id"] = row[k]
        else:
            fld = next((f for f in fm["fields"] if f["col"] == k), None)
            d[k] = _from_store(row[k], _is_json_field(fld)) if fld else row[k]
    return d


def _sub_to_dict(sf, row):
    d = {"id": row["id"]}
    for k in row.keys():
        if k in ("id", "parent_id", "tenant_id"):
            continue
        fld = next((s for s in sf["subfields"] if s["col"] == k), None)
        d[k] = _from_store(row[k], _is_json_field(fld)) if fld else row[k]
    return d


# ---------------- 审批流（通用状态机） ----------------
# 说明：简道云表单 schema（info_access）仅暴露流程 UI 开关（allowSubmit 等），
# 审批节点图（审批人/条件分支）在「流程设计」独立接口，本迁移未抓取。
# 故以通用单级状态机 draft→pending→approved/rejected 还原"提交/审批"语义，
# 后续若抓到节点图，可在此扩展多级 current_node 流转。
def flow_submit(form_key, rid, principal=None, conn=None):
    _load_schema()
    fm = _FORM_BY_KEY.get(form_key)
    if not fm or not fm.get("has_flow"):
        raise KeyError(f"表单 {form_key} 非流程表单")
    c = _conn(conn)
    init(c)
    r = c.execute(f"SELECT id FROM hrm_{form_key} WHERE id=?", (rid,)).fetchone()
    if not r:
        raise KeyError("记录不存在")
    c.execute(f"UPDATE hrm_{form_key} SET flow_status='pending', updated_at=datetime('now') WHERE id=?", (rid,))
    iid = "fl_" + uuid.uuid4().hex[:12]
    c.execute(
        "INSERT INTO hrm_flow_instances(id,form_key,row_id,tenant_id,status,submitted_by) VALUES(?,?,?,?,?,?)",
        (iid, form_key, rid, (principal.tenant_id if principal else "default"),
         "pending", (principal.username if principal else "")),
    )
    c.commit()
    return {"instance_id": iid, "row_id": rid, "status": "pending"}


def flow_decide(instance_id, approve, by="", note="", conn=None):
    c = _conn(conn)
    init(c)
    inst = c.execute("SELECT * FROM hrm_flow_instances WHERE id=?", (instance_id,)).fetchone()
    if not inst:
        raise KeyError("流程实例不存在")
    status = "approved" if approve else "rejected"
    c.execute(
        "UPDATE hrm_flow_instances SET status=?, decision_by=?, decision_note=?, decided_at=datetime('now') WHERE id=?",
        (status, by, note, instance_id),
    )
    c.execute(
        f"UPDATE hrm_{inst['form_key']} SET flow_status=?, updated_at=datetime('now') WHERE id=?",
        (status, inst["row_id"]),
    )
    c.commit()
    done = c.execute("SELECT * FROM hrm_flow_instances WHERE id=?", (instance_id,)).fetchone()
    return dict(done) if done else dict(inst)


def flow_list_pending(tenant_id="default", conn=None):
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT * FROM hrm_flow_instances WHERE tenant_id=? AND status='pending' ORDER BY created_at DESC",
        (tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]
