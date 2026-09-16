"""模块五 · 劳动关系：合同台账 + 第14条无固定期限预警 + 试用期提醒 + 自动待办。

移植自 hr-ai-workbench/app/services/reminders.py 的「到期提醒规则引擎」，
SQL 化落地（MiniYuxi 用裸 sqlite3，db.py 为不可改指纹，故新表走运行时 CREATE TABLE）。

设计：
- 全部表走 init() 内 CREATE TABLE IF NOT EXISTS，不碰冻结 db.py；
- sync_contract_todos() 幂等：先清该合同 open 待办再重生成，可重复安全执行；
- 第14条预警：第2次及以上合同、距到期 <= second_expire 天，提示应订无固定期限
  （劳动合同法第14条），并附「另有第39条、第40条第1/2项情形的除外。本提示不构成法律意见。」；
- 贴合在办案件：contract 的 note 字段可写入「车务通/陕西导航混同用工」等关联风险提示。
"""
from datetime import date, datetime

from . import db


# 预警天数配置（与 hr-ai-workbench reminder 配置对齐，可在此集中调整）
CONTRACT_EXPIRE_DAYS = [60, 30, 7]      # 合同到期前提醒档位
CONTRACT_2ND_EXPIRE_DAYS = 90           # 第2次及以上合同「第14条」预警窗口
PROBATION_EXPIRE_DAYS = [15, 7]         # 试用期到期提醒档位


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS contracts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT DEFAULT 'default',
                name TEXT NOT NULL,
                personnel TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                is_indefinite INTEGER DEFAULT 0,
                contract_no INTEGER DEFAULT 1,
                contract_type TEXT DEFAULT '固定期限',
                status TEXT DEFAULT '履行中',
                probation_start TEXT,
                probation_end TEXT,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS labor_todos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT DEFAULT 'default',
                title TEXT NOT NULL,
                kind TEXT DEFAULT 'contract',
                ref_id INTEGER DEFAULT 0,
                due_date TEXT,
                level TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'open',
                source TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def _today() -> date:
    return date.today()


def _parse(d):
    if not d:
        return None
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


# ------------------------------------------------------------------ 合同 CRUD
def upsert_contract(tenant_id="default", conn=None, **kw) -> int:
    """新增或更新合同。kw 可含 name/personnel/start_date/end_date/is_indefinite/
    contract_no/contract_type/status/probation_start/probation_end/note，及 id(更新时)。"""
    c = _conn(conn)
    init(c)
    cur = c.cursor()
    cid = kw.get("id")
    fields = ["name", "personnel", "start_date", "end_date", "is_indefinite",
              "contract_no", "contract_type", "status", "probation_start",
              "probation_end", "note"]
    if cid:
        sets = ", ".join(f"{f}=?" for f in fields) + ", updated_at=datetime('now')"
        vals = [kw.get(f) for f in fields] + [cid]
        cur.execute(f"UPDATE contracts SET {sets} WHERE id=?", vals)
    else:
        cols = ", ".join(["tenant_id"] + fields)
        ph = ", ".join(["?"] * (len(fields) + 1))
        vals = [tenant_id] + [kw.get(f) for f in fields]
        cur.execute(f"INSERT INTO contracts({cols}) VALUES({ph})", vals)
        cid = cur.lastrowid
    c.commit()
    return cid


def list_contracts(tenant_id="default", status=None, conn=None) -> list:
    c = _conn(conn)
    init(c)
    if status:
        rows = c.execute(
            "SELECT * FROM contracts WHERE tenant_id=? AND status=? ORDER BY end_date",
            (tenant_id, status)).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM contracts WHERE tenant_id=? ORDER BY end_date",
            (tenant_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_contract(cid, conn=None) -> bool:
    c = _conn(conn)
    init(c)
    c.execute("DELETE FROM contracts WHERE id=?", (cid,))
    c.execute("DELETE FROM labor_todos WHERE kind='contract' AND ref_id=?", (cid,))
    c.commit()
    return True


# ------------------------------------------------------------------ 待办
def add_todo(tenant_id, title, kind, ref_id, due, level, source, note="", conn=None) -> int:
    c = _conn(conn)
    init(c)
    cur = c.cursor()
    cur.execute(
        "INSERT INTO labor_todos(tenant_id,title,kind,ref_id,due_date,level,status,source,note) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (tenant_id, title, kind, ref_id, due, level, "open", source, note))
    tid = cur.lastrowid
    c.commit()
    return tid


def _clear_open(c, kind, ref_id):
    c.execute(
        "UPDATE labor_todos SET status='cleared' WHERE kind=? AND ref_id=? AND status='open'",
        (kind, ref_id))


def list_todos(tenant_id="default", status="open", conn=None) -> list:
    c = _conn(conn)
    init(c)
    rows = c.execute(
        "SELECT * FROM labor_todos WHERE tenant_id=? AND status=? ORDER BY "
        "CASE level WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date",
        (tenant_id, status)).fetchall()
    return [dict(r) for r in rows]


def resolve_todo(tid, conn=None) -> bool:
    c = _conn(conn)
    init(c)
    c.execute("UPDATE labor_todos SET status='done', resolved_at=datetime('now') WHERE id=?",
              (tid,))
    c.commit()
    return True


# ------------------------------------------------------------------ 预警引擎
def sync_contract_todos(tenant_id="default", conn=None) -> dict:
    """扫描全部合同，幂等生成待办。返回统计。"""
    c = _conn(conn)
    init(c)
    today = _today()
    expire_days = sorted(CONTRACT_EXPIRE_DAYS, reverse=True)
    second_expire = CONTRACT_2ND_EXPIRE_DAYS
    probation_days = sorted(PROBATION_EXPIRE_DAYS, reverse=True)

    contracts = c.execute(
        "SELECT * FROM contracts WHERE tenant_id=? AND status IN ('履行中','待签')",
        (tenant_id,)).fetchall()

    gen = 0
    for ct in contracts:
        cid = ct["id"]
        _clear_open(c, "contract", cid)

        # —— 合同到期 ——
        end = _parse(ct["end_date"])
        if not ct["is_indefinite"] and end:
            days = (end - today).days
            due = ct["end_date"]
            if days < 0:
                add_todo(tenant_id,
                         f"合同已到期：{ct['personnel']}《{ct['name']}》（{ct['end_date']}）",
                         "contract", cid, due, "urgent", "合同到期扫描",
                         "请立即处理续签/终止手续，避免事实劳动关系风险。", conn=c)
                gen += 1
            else:
                for d in expire_days:
                    if days <= d:
                        level = "urgent" if d <= 7 else ("high" if d <= 30 else "medium")
                        add_todo(tenant_id,
                                 f"合同将于{days}天后到期：{ct['personnel']}《{ct['name']}》（{ct['end_date']}）",
                                 "contract", cid, due, level, "合同到期扫描",
                                 f"到期前{d}天提醒（规则配置）。", conn=c)
                        gen += 1
                        break
            # 第2次及以上合同特别预警（下次应为无固定期限）
            if ct["contract_no"] and ct["contract_no"] >= 2 and days <= second_expire:
                extra = (("；关联提示：" + ct["note"]) if ct["note"] else "")
                add_todo(tenant_id,
                         f"第{ct['contract_no']}次合同即将到期：{ct['personnel']}（{ct['end_date']}）"
                         f"——按劳动合同法第14条，本次续订时除劳动者本人提出订立固定期限外，"
                         f"应当订立无固定期限劳动合同",
                         "contract", cid, due, "high", "第2次合同预警",
                         "另有第39条、第40条第1/2项情形的除外。本提示不构成法律意见。" + extra,
                         conn=c)
                gen += 1

        # —— 试用期到期 ——
        pEnd = _parse(ct["probation_end"])
        if pEnd:
            pdays = (pEnd - today).days
            for d in probation_days:
                if pdays <= d:
                    if pdays < 0:
                        add_todo(tenant_id,
                                 f"试用期已结束：{ct['personnel']}（{ct['probation_end']}），转正评估待补",
                                 "contract", cid, ct["probation_end"], "high", "试用期扫描",
                                 conn=c)
                    else:
                        add_todo(tenant_id,
                                 f"试用期将于{pdays}天后到期：{ct['personnel']}（{ct['probation_end']}），请发起转正评估",
                                 "contract", cid, ct["probation_end"], "high", "试用期扫描",
                                 conn=c)
                    gen += 1
                    break

    c.commit()
    return {"generated": gen, "scanned": len(contracts), "tenant_id": tenant_id}


def sync_all(tenant_id="default", conn=None) -> dict:
    """劳动关系全量重扫（合同预警）。供调度与手动触发统一调用。"""
    return sync_contract_todos(tenant_id, conn)


def dashboard(tenant_id="default", conn=None) -> dict:
    """待办/合同概览，供前端展示与一键排查。"""
    c = _conn(conn)
    init(c)
    open_todos = list_todos(tenant_id, "open", c)
    contracts = list_contracts(tenant_id, conn=c)
    by_level = {}
    for t in open_todos:
        by_level[t["level"]] = by_level.get(t["level"], 0) + 1
    urgent = [t for t in open_todos if t["level"] in ("urgent", "high")]
    return {
        "tenant_id": tenant_id,
        "open_todo_count": len(open_todos),
        "todos_by_level": by_level,
        "contract_count": len(contracts),
        "urgent_todos": urgent[:10],
    }
