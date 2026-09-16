"""模块四补充 · 薪酬明细与工资答疑：工资台账 + 确定性答疑助手。

移植自 hr-ai-workbench 的 SalaryRecord 模型与「工资答疑」思路，SQL 化落地。
与已存在的 salary_assist（谈薪辅助/市场分位）互补——本模块管「已发工资明细台账」
与「员工提问的确定性答疑」，不涉及谈薪策略。

设计：
- salary_records 表走 init() 运行时建表，不碰冻结 db.py；
- salary_qa() 为纯规则答疑：实发=应发-社保-公积金-个税-其他扣；个税起征点 5000；
  可接 LLM 做口语化润色（缺失 Key 不阻断）。
"""
from . import db, config

# 个税起征点（基本减除费用，单位：元/月）
TAX_THRESHOLD = 5000


def init(conn=None):
    c = conn or db.connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS salary_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT DEFAULT 'default',
                emp_name TEXT NOT NULL,
                month TEXT DEFAULT '',
                base_salary INTEGER DEFAULT 0,
                performance INTEGER DEFAULT 0,
                subsidy INTEGER DEFAULT 0,
                overtime_pay INTEGER DEFAULT 0,
                social_insurance INTEGER DEFAULT 0,
                housing_fund INTEGER DEFAULT 0,
                tax INTEGER DEFAULT 0,
                other_deduct INTEGER DEFAULT 0,
                net_salary INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        c.commit()
    except Exception:
        pass


def _conn(conn):
    return conn or db.connect()


def _gross(r: dict) -> int:
    return (r.get("base_salary", 0) + r.get("performance", 0) +
            r.get("subsidy", 0) + r.get("overtime_pay", 0))


def _net(r: dict) -> int:
    return (_gross(r) - r.get("social_insurance", 0) - r.get("housing_fund", 0)
            - r.get("tax", 0) - r.get("other_deduct", 0))


def add_record(tenant_id="default", conn=None, **kw) -> int:
    """新增一条工资明细。可含 emp_name/month/base_salary/performance/subsidy/
    overtime_pay/social_insurance/housing_fund/tax/other_deduct/note，及 id(更新)。"""
    c = _conn(conn)
    init(c)
    rid = kw.get("id")
    fields = ["emp_name", "month", "base_salary", "performance", "subsidy",
              "overtime_pay", "social_insurance", "housing_fund", "tax",
              "other_deduct", "note"]
    for f in fields:
        if f not in ("emp_name", "month", "note") and kw.get(f) is None:
            kw[f] = 0
    rec = {f: kw.get(f) for f in fields}
    rec["net_salary"] = _net(rec)
    if rid:
        sets = ", ".join(f"{f}=?" for f in fields) + ", net_salary=?"
        c.execute(f"UPDATE salary_records SET {sets} WHERE id=?",
                  [rec[f] for f in fields] + [rec["net_salary"], rid])
    else:
        cur = c.cursor()
        cols = ", ".join(["tenant_id"] + fields + ["net_salary"])
        ph = ", ".join(["?"] * (len(fields) + 2))
        cur.execute(f"INSERT INTO salary_records({cols}) VALUES({ph})",
                    [tenant_id] + [rec[f] for f in fields] + [rec["net_salary"]])
        rid = cur.lastrowid
    c.commit()
    return rid


def list_records(tenant_id="default", month=None, emp_name=None, conn=None) -> list:
    c = _conn(conn)
    init(c)
    sql = "SELECT * FROM salary_records WHERE tenant_id=?"
    args = [tenant_id]
    if month:
        sql += " AND month=?"
        args.append(month)
    if emp_name:
        sql += " AND emp_name=?"
        args.append(emp_name)
    sql += " ORDER BY month DESC, emp_name"
    rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def month_summary(tenant_id="default", month=None, conn=None) -> dict:
    c = _conn(conn)
    init(c)
    sql = ("SELECT COUNT(*) n, SUM(base_salary) base, SUM(performance) perf, "
           "SUM(subsidy) sub, SUM(overtime_pay) ot, SUM(social_insurance) si, "
           "SUM(housing_fund) hf, SUM(tax) tax, SUM(other_deduct) od, SUM(net_salary) net "
           "FROM salary_records WHERE tenant_id=?")
    args = [tenant_id]
    if month:
        sql += " AND month=?"
        args.append(month)
    row = c.execute(sql, args).fetchone()
    return {k: (row[k] or 0) for k in
            ("n", "base", "perf", "sub", "ot", "si", "hf", "tax", "od", "net")} | {"month": month}


# ------------------------------------------------------------------ 工资答疑
def salary_qa(question: str, tenant_id="default", conn=None) -> dict:
    """确定性答疑：覆盖「实发怎么算」「个税起征点」「社保公积金」「某员工某月明细」。

    返回 {answer, calc, refs}。calc 为可复核的数字明细；refs 为政策依据。
    LLM 仅做可选口语化润色，缺失 Key 不阻断。"""
    q = (question or "").strip()
    c = _conn(conn)
    init(c)
    calc, refs = {}, []

    # 1) 实发工资算法（通用规则）
    if any(k in q for k in ("实发", "到手", "怎么算", "计算公式", "构成")):
        calc = {
            "应发=基本工资+绩效+补贴+加班费",
            "实发=应发-个人社保-个人公积金-个税-其他扣款",
            "个税起征点=5000 元/月（基本减除费用）",
        }
        answer = ("实发工资 = 应发工资 − 个人社保 − 个人公积金 − 个人所得税 − 其他扣款；"
                  "其中应发 = 基本工资 + 绩效 + 补贴 + 加班费。个税基本减除费用为 5000 元/月。")
        refs.append("《个人所得税法》第六条（基本减除费用 5000 元/月）")
        return {"answer": answer, "calc": list(calc), "refs": refs}

    # 2) 个税起征点
    if "起征点" in q or "个税" in q or "所得税" in q:
        answer = f"个税基本减除费用为 {TAX_THRESHOLD} 元/月；超过部分按累计预扣法计算，具体税率随累计应纳税所得额跳档。"
        refs.append("《个人所得税法》第六条")
        return {"answer": answer, "calc": [f"基本减除费用={TAX_THRESHOLD}"], "refs": refs}

    # 3) 社保/公积金
    if "社保" in q or "公积金" in q or "五险一金" in q:
        answer = ("个人承担部分从工资中代扣：养老保险约 8%、医疗保险约 2%、失业保险约 0.5%，"
                  "住房公积金 5%–12%（由单位在规定区间确定）。缴费基数一般为上年度月平均工资，"
                  "并受当地上下限约束。")
        refs.append("《社会保险法》; 《住房公积金管理条例》")
        return {"answer": answer, "calc": ["养老≈8%", "医疗≈2%", "失业≈0.5%", "公积金5%-12%"], "refs": refs}

    # 4) 查某人某月工资明细
    import re
    name_m = re.search(r"([\u4e00-\u9fa5]{2,4})", q)
    month_m = re.search(r"(20\d{2}[-/年]\d{1,2}(?:月)?|\d{4}-\d{2})", q)
    if name_m and ("多少" in q or "明细" in q or "工资" in q or "发" in q):
        emp = name_m.group(1)
        month = None
        if month_m:
            mm = month_m.group(1).replace("年", "-").replace("月", "").replace("/", "-")
            parts = mm.split("-")
            if len(parts) == 2:
                month = f"{int(parts[0]):04d}-{int(parts[1]):02d}"
        recs = list_records(tenant_id, month, emp, c)
        if recs:
            r = recs[0]
            net = r.get("net_salary") or _net(r)
            answer = (f"{emp}（{r['month']}）应发 {_gross(r)} 元，个人社保 {r['social_insurance']}、"
                      f"公积金 {r['housing_fund']}、个税 {r['tax']}、其他扣 {r['other_deduct']}，"
                      f"实发 {net} 元。")
            calc = {"应发": _gross(r), "社保": r["social_insurance"],
                    "公积金": r["housing_fund"], "个税": r["tax"],
                    "其他扣": r["other_deduct"], "实发": net}
            return {"answer": answer, "calc": calc, "refs": ["工资台账记录"]}
        else:
            answer = f"未查询到 {emp}" + (f" 在 {month} 的工资记录。" if month else " 的工资记录。")
            return {"answer": answer, "calc": {}, "refs": []}

    # 5) 兜底
    answer = ("我可解答：实发工资计算公式、个税起征点、社保/公积金代扣比例，"
              "以及查询某员工某月工资明细（请带上姓名与月份）。具体金额以公司薪酬制度与当地政策为准。")
    return {"answer": answer, "calc": {}, "refs": []}
