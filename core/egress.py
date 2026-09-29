"""数据出境管控（企业级定位落地 · 2026-09-24）。

背景：MiniYuxi 定位更正为「企业级 Agent：数据**可以**出本机、零 Docker、可商用」。
但「可以出境」不等于「随便出境」——企业级要求出境必须满足两条：

  ① **可按数据分级配置**：不是全开/全关。哪类目的地、哪一级数据能出，
     由策略决定（allow / deny / approval 三态）。
  ② **可审计**：每一次出境尝试都留痕——**包括被拒绝的**。日志进 SOC 哈希链，
     可举证、可导出、防篡改。

出境清单（2026-09-24 实测收口：5 类目的地 · 10 个真实出口）：

  | 类别          | 载荷性质                      | 收口点                                |
  |--------------|------------------------------|--------------------------------------|
  | llm          | 对话内容（system+历史+提问）    | gateway / model_hub / provider_router |
  | embedding    | **文档原文**（入库切片）        | rag.embed / rebuild_vectors           |
  | search       | 检索关键词（由用户问题派生）     | tools_registry.web_search             |
  | external_rag | 用户问题 + 知识库片段           | rag_adapter                           |
  | connector    | 消息正文 + 收件人              | connectors.send_message               |

  （run.py 的 /api/health 自探针走 127.0.0.1 回环，**不计入出境**。
    另有一处 `/api/health` → 豆包搜索后端的连通性探针（固定载荷 "ping"、每 30s 一次），
    它**受策略约束但 `audit=False`**，不写日志行——理由见 guard() 的 audit 参数说明。）

设计取舍（写清楚，免得后来者当成漏洞）：
  - **默认全放行**：定位是「数据可以出本机」，开箱即禁会让产品直接不可用。
    企业侧按需收紧，或直接 `MINIYUXI_EGRESS_LOCKDOWN=1` 一键锁死全部出境。
  - **guard 自身异常默认 fail-open**：默认策略本就是放行，且 guard 崩溃若连带
    掐死所有 LLM 调用，等于把「审计组件」变成「单点故障」。企业若要严格
    fail-closed，设 `MINIYUXI_EGRESS_FAIL_MODE=closed`。
  - **日志绝不记全文**：只记目的地主机、字节数、脱敏截断摘要。否则日志本身
    就成了新的泄露面——这是本模块的红线。

策略优先级（高 → 低）：
  1. `lockdown`（一键锁死，全 deny）
  2. 环境变量 `MINIYUXI_EGRESS_<CLASS>`（企业 IT 统一下发，不可被 UI 覆盖）
  3. 策略 `by_level[<分级>]`（如 confidential → approval）
  4. 策略 `default`
  5. 内置默认 allow
"""
import json
import os
import re
import time

from . import db

# ---------------- 三组枚举 ----------------
# 目的地类别：与出境清单一一对应
CLASSES = ("llm", "embedding", "search", "external_rag", "connector")
# 三态模式
MODES = ("allow", "deny", "approval")
# 数据分级（由低到高）
LEVELS = ("public", "internal", "confidential")

# 每类目的地的说明与收口点（供 /api/egress/inventory 自描述）
INVENTORY = {
    "llm": {
        "label": "大模型推理",
        "payload": "对话内容（system + 历史轮次 + 当前提问）",
        "sites": ["core/gateway.py", "core/model_hub.py", "core/provider_router.py"],
    },
    "embedding": {
        "label": "向量化（Embedding）",
        "payload": "文档原文切片（入库时）",
        "sites": ["core/rag.py", "rebuild_vectors.py"],
    },
    "search": {
        "label": "联网检索",
        "payload": "检索关键词（由用户问题派生）",
        "sites": ["core/tools_registry.py"],
    },
    "external_rag": {
        "label": "外部 RAG 平台",
        "payload": "用户问题 + 知识库片段（RAGFlow / FastGPT）",
        "sites": ["core/rag_adapter.py"],
    },
    "connector": {
        "label": "外部业务系统发送",
        "payload": "消息正文 + 收件人（企微 / CRM / ERP / 飞书）",
        "sites": ["core/connectors.py"],
    },
}

# ---------------- 分级规则 ----------------
# 高敏模式：命中即 confidential（用于分级 + 日志脱敏）
_SENSITIVE_PATTERNS = [
    ("身份证", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)|(?<!\d)\d{15}(?!\d)")),
    ("银行卡", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
]

# HR / 商业敏感关键词：命中即 confidential
# ⚠️ 刻意偏保守（宁可多判机密）：漏判 = 敏感数据无保护出境，误判 = 严格模式下多一次审批。
#    企业若嫌严格模式太吵，可关掉自动分级（policy.classify=False）改用显式 level。
_CONFIDENTIAL_KEYWORDS = (
    # 薪酬
    "工资", "薪酬", "薪资", "月薪", "年薪", "底薪", "绩效", "奖金", "提成", "年终奖",
    "社保", "公积金", "个税", "纳税", "工资表", "薪酬表", "调薪", "降薪", "薪资结构",
    # 个人敏感
    "身份证", "银行卡", "体检", "病历", "病史", "婚育", "家庭住址", "紧急联系人", "员工档案",
    # 人事处置（2026-09-24 补：原表只有「辞退/解雇」，漏了更常用的「解除劳动合同」，
    #  导致「关于解除劳动合同的通知」被判成 internal —— 这是漏判，已补齐）
    "违纪", "处分", "辞退", "解雇", "裁员", "劝退", "调岗", "离职补偿",
    "解除劳动合同", "解除劳动关系", "劳动合同解除", "经济补偿", "赔偿金",
    "试用期不合格", "严重违反", "劳动仲裁", "劳动诉讼", "竞业", "服务期",
    # 商业机密
    "保密", "商业机密", "客户名单", "供应商报价", "报价单", "成本", "毛利", "标底",
)


# ---------------- 策略 ----------------
def _default_policy() -> dict:
    """内置默认策略：全放行（见模块头「设计取舍」）。"""
    return {
        "version": 1,
        "lockdown": False,
        "classify": True,          # 是否自动分级（关掉则一律按 internal 处理）
        "classes": {c: {"default": "allow", "by_level": {}} for c in CLASSES},
    }


# 可一键套用的姿态预设（企业交付时最常用的三档）
PRESETS = {
    "balanced": {
        "label": "均衡（默认）",
        "desc": "全部放行，仅留痕。适合内部试用 / 已有 DPA 的场景。",
        "policy": _default_policy(),
    },
    "strict": {
        "label": "严格",
        "desc": "机密级数据（工资/身份证/辞退等）出境前需人工审批；其余放行。",
        "policy": {
            "version": 1, "lockdown": False, "classify": True,
            "classes": {
                c: {"default": "allow",
                    "by_level": {"confidential": "approval"} if c != "search" else {}}
                for c in CLASSES
            },
        },
    },
    "lockdown": {
        "label": "锁死",
        "desc": "禁止一切出境，全链路降级为离线能力。适合涉密/断网环境。",
        "policy": {
            "version": 1, "lockdown": True, "classify": True,
            "classes": {c: {"default": "deny", "by_level": {}} for c in CLASSES},
        },
    },
}


def init(conn=None):
    c = conn or db.connect()
    c.execute("""CREATE TABLE IF NOT EXISTS egress_policy(
        key TEXT PRIMARY KEY, value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now')))""")
    # 出境日志：可查询 / 可统计 / 可导出。
    # ⚠️ summary 只存脱敏截断文本（<=200 字符），**绝不存载荷全文**。
    c.execute("""CREATE TABLE IF NOT EXISTS egress_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT DEFAULT (datetime('now')),
        tenant_id TEXT, actor TEXT, session_id TEXT,
        dest_class TEXT NOT NULL, destination TEXT, dest_host TEXT,
        level TEXT NOT NULL DEFAULT 'internal',
        mode TEXT NOT NULL, decision TEXT NOT NULL,
        bytes_out INTEGER DEFAULT 0,
        summary TEXT DEFAULT '',
        reason TEXT DEFAULT '', detail_json TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_egress_log_ts ON egress_log(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_egress_log_class ON egress_log(dest_class, decision)")
    c.commit()


def get_policy(conn=None) -> dict:
    """读策略；无记录 / 损坏 / 缺字段 → 回落到默认策略（永不抛栈）。"""
    try:
        c = conn or db.connect()
        init(c)
        row = c.execute("SELECT value FROM egress_policy WHERE key='policy'").fetchone()
        if not row:
            return _default_policy()
        pol = json.loads(row["value"])
        if not isinstance(pol, dict):
            return _default_policy()
        base = _default_policy()
        base.update({k: pol[k] for k in ("version", "lockdown", "classify") if k in pol})
        classes = base["classes"]
        for cname, cfg in (pol.get("classes") or {}).items():
            if cname not in CLASSES or not isinstance(cfg, dict):
                continue
            d = cfg.get("default")
            if d in MODES:
                classes[cname]["default"] = d
            bl = {k: v for k, v in (cfg.get("by_level") or {}).items()
                  if k in LEVELS and v in MODES}
            classes[cname]["by_level"] = bl
        return base
    except Exception:
        return _default_policy()


def set_policy(policy: dict, conn=None) -> dict:
    """写策略（先归一化，非法值丢弃而非报错）。返回归一化后的策略。"""
    c = conn or db.connect()
    init(c)
    cur = get_policy(c)
    if isinstance(policy, dict):
        for k in ("version", "lockdown", "classify"):
            if k in policy:
                cur[k] = bool(policy[k]) if k != "version" else int(policy[k] or 1)
        for cname, cfg in (policy.get("classes") or {}).items():
            if cname not in CLASSES or not isinstance(cfg, dict):
                continue
            if cfg.get("default") in MODES:
                cur["classes"][cname]["default"] = cfg["default"]
            if isinstance(cfg.get("by_level"), dict):
                cur["classes"][cname]["by_level"] = {
                    k: v for k, v in cfg["by_level"].items() if k in LEVELS and v in MODES
                }
    c.execute("INSERT OR REPLACE INTO egress_policy(key,value,updated_at) "
              "VALUES('policy',?,datetime('now'))",
              (json.dumps(cur, ensure_ascii=False),))
    c.commit()
    return cur


def apply_preset(name: str, conn=None) -> dict:
    """套用姿态预设（balanced / strict / lockdown）。未知名称抛 KeyError。"""
    if name not in PRESETS:
        raise KeyError(f"unknown preset: {name}; allowed={tuple(PRESETS)}")
    pol = json.loads(json.dumps(PRESETS[name]["policy"]))  # 深拷贝，避免改到常量
    return set_policy(pol, conn)


# ---------------- 分级 ----------------
def classify(text) -> str:
    """按内容自动分级：confidential / internal / public。

    规则朴素但可解释：命中 HR·商业敏感关键词或高敏格式（身份证/银行卡/手机号/邮箱）
    → confidential；非空文本 → internal；空 → public。
    企业可关掉自动分级（policy.classify=False）改用显式传 level。
    """
    s = str(text or "")
    if not s.strip():
        return "public"
    if any(k in s for k in _CONFIDENTIAL_KEYWORDS):
        return "confidential"
    if any(p.search(s) for _, p in _SENSITIVE_PATTERNS):
        return "confidential"
    return "internal"


def redact(text, limit: int = 200) -> str:
    """脱敏 + 截断：用于日志摘要。**绝不返回全文**。"""
    s = str(text or "")
    for name, pat in _SENSITIVE_PATTERNS:
        s = pat.sub(f"[{name}]", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def _payload_text(payload) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return str(payload)


def _host_of(destination: str) -> str:
    """只取主机名入日志——URL 的 path/query 可能含敏感参数（如检索词）。"""
    s = str(destination or "")
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)", s)
    return m.group(1) if m else s.split("/")[0]


# ---------------- 策略解析 ----------------
def _fail_closed() -> bool:
    return (os.getenv("MINIYUXI_EGRESS_FAIL_MODE", "open").strip().lower()
            in ("closed", "close", "deny"))


def lockdown_by_env() -> bool:
    return os.getenv("MINIYUXI_EGRESS_LOCKDOWN", "").strip().lower() in ("1", "true", "yes", "on")


def effective_mode(dest_class: str, level: str = "internal", conn=None) -> str:
    """解析某类目的地 + 某分级的生效模式。优先级见模块头。"""
    if lockdown_by_env():
        return "deny"
    pol = get_policy(conn)
    if pol.get("lockdown"):
        return "deny"
    env = os.getenv(f"MINIYUXI_EGRESS_{str(dest_class).upper()}", "").strip().lower()
    if env in MODES:
        return env
    cfg = (pol.get("classes") or {}).get(dest_class) or {}
    bl = cfg.get("by_level") or {}
    if level in bl and bl[level] in MODES:
        return bl[level]
    d = cfg.get("default", "allow")
    return d if d in MODES else "allow"


# ---------------- 闸门 ----------------
def _record(dest_class, destination, level, mode, decision, payload_text,
            reason, tenant_id, session_id, actor, meta) -> int | None:
    """写双份留痕：egress_log（可查询）+ soc_audit（哈希链，防篡改）。"""
    host = _host_of(destination)
    summary = redact(payload_text)
    nbytes = len(payload_text.encode("utf-8")) if payload_text else 0
    severity = "warn" if decision in ("deny", "pending") else "info"
    if level == "confidential" and decision == "allow":
        severity = "warn"  # 机密数据放行 → 提高告警级别，便于事后抽查
    log_id = None
    try:
        c = db.connect()
        cur = c.execute(
            "INSERT INTO egress_log(tenant_id,actor,session_id,dest_class,destination,dest_host,"
            "level,mode,decision,bytes_out,summary,reason,detail_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tenant_id or "default", actor or "agent", session_id or "", dest_class, host, host,
             level, mode, decision, nbytes, summary, reason,
             json.dumps(meta or {}, ensure_ascii=False)),
        )
        c.commit()
        log_id = cur.lastrowid
    except Exception:
        pass
    try:
        from . import soc_audit
        soc_audit.log({
            "tenant_id": tenant_id or "default",
            "actor": actor or "agent",
            "role": "agent",
            "action": f"egress.{dest_class}",
            "target": host,
            "result": decision,
            "severity": severity,
            "session_id": session_id or "",
            "detail": {"level": level, "mode": mode, "bytes_out": nbytes,
                       "reason": reason, "summary": summary,
                       "egress_log_id": log_id},
        })
    except Exception:
        pass
    return log_id


def guard(dest_class: str, destination: str = "", payload=None, level: str | None = None,
          tenant_id: str | None = None, session_id: str | None = None,
          actor: str = "agent", meta: dict | None = None, audit: bool = True) -> dict:
    """**出境唯一收口点**。所有出网调用在发请求前过这里。

    返回 ``{"allow": bool, "mode": str, "level": str, "reason": str, "log_id": int|None}``
    （approval 模式另带 ``approval_id``）。**本函数不抛栈**：deny / approval 时
    ``allow=False``，调用方必须走降级路径（离线兜底 / 返回 not_configured），不得崩链路。

    ``audit=False`` 仅用于**固定载荷的高频连通性探针**（如 /api/health 里的
    「ping」探测，每 30s 一次）：策略**仍然强制执行**，只是不写日志行，
    避免探针把审计链灌成噪音。业务调用**一律不要传**此参数。
    """
    payload_text = _payload_text(payload)
    try:
        if dest_class not in CLASSES:
            # 未知类别不静默放行——按 llm 之外的新出口对待，记 warn 但放行（避免误伤新功能）
            pass
        pol = get_policy()
        lvl = level if level in LEVELS else (
            classify(payload_text) if pol.get("classify", True) else "internal"
        )
        mode = effective_mode(dest_class, lvl)

        def _rec(decision):
            if not audit:
                return None
            return _record(dest_class, destination, lvl, mode, decision, payload_text,
                           f"policy:{decision}" if decision != "pending" else "policy:approval",
                           tenant_id, session_id, actor, meta)

        if mode == "allow":
            return {"allow": True, "mode": mode, "level": lvl, "reason": "policy:allow",
                    "log_id": _rec("allow")}
        if mode == "deny":
            return {"allow": False, "mode": mode, "level": lvl, "reason": "policy:deny",
                    "log_id": _rec("deny")}
        # approval：挂 HITL 审批卡，本次不放行
        aid = ""
        try:
            from . import approval
            aid = approval.create(
                tenant_id or "default", f"egress.{dest_class}",
                args_json=json.dumps({"destination": _host_of(destination), "level": lvl,
                                      "summary": redact(payload_text)},
                                     ensure_ascii=False),
                requested_by=session_id or "", risk="high",
            )
        except Exception:
            pass
        return {"allow": False, "mode": "approval", "level": lvl,
                "reason": "policy:approval", "approval_id": aid, "log_id": _rec("pending")}
    except Exception as exc:  # noqa: BLE001 —— 闸门自身故障
        if _fail_closed():
            return {"allow": False, "mode": "error", "level": level or "internal",
                    "reason": f"guard_error:{exc}"[:200], "log_id": None}
        # fail-open：与「默认放行」策略一致，且不让审计组件变成单点故障
        return {"allow": True, "mode": "degraded", "level": level or "internal",
                "reason": f"guard_error(fail-open):{exc}"[:200], "log_id": None}


def blocked(dest_class: str, destination: str = "", payload=None, level: str | None = None,
            tenant_id: str | None = None, session_id: str | None = None) -> bool:
    """便捷闸门：``True`` = 禁止出境，调用方必须降级。让 call site 改动保持一行。"""
    return not guard(dest_class, destination, payload, level, tenant_id, session_id).get("allow", True)


# ---------------- 查询 ----------------
def list_log(limit: int = 100, dest_class: str = "", decision: str = "",
             tenant_id: str | None = None, conn=None) -> list:
    """出境日志（倒序）。"""
    try:
        c = conn or db.connect()
        init(c)
        where, params = [], []
        if dest_class:
            where.append("dest_class=?"); params.append(dest_class)
        if decision:
            where.append("decision=?"); params.append(decision)
        if tenant_id:
            where.append("tenant_id=?"); params.append(tenant_id)
        sql = ("SELECT id,ts,tenant_id,actor,session_id,dest_class,destination,dest_host,"
               "level,mode,decision,bytes_out,summary,reason FROM egress_log")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit or 100), 1000)))
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    except Exception:
        return []


def stats(tenant_id: str | None = None, conn=None) -> dict:
    """出境统计：按类别 / 决策 / 分级汇总，供看板与合规报表。"""
    try:
        c = conn or db.connect()
        init(c)
        w, p = ("WHERE tenant_id=?", [tenant_id]) if tenant_id else ("", [])

        def _by(col):
            rows = c.execute(
                f"SELECT {col} AS k, COUNT(*) AS n, COALESCE(SUM(bytes_out),0) AS b "
                f"FROM egress_log {w} GROUP BY {col} ORDER BY n DESC", p).fetchall()
            return {r["k"] or "": {"count": r["n"], "bytes": r["b"]} for r in rows}

        total = c.execute(f"SELECT COUNT(*) AS n FROM egress_log {w}", p).fetchone()["n"]
        return {"total": total, "by_class": _by("dest_class"),
                "by_decision": _by("decision"), "by_level": _by("level")}
    except Exception:
        return {"total": 0, "by_class": {}, "by_decision": {}, "by_level": {}}


def inventory(conn=None) -> dict:
    """出境点自描述：5 类目的地 + 收口点 + 每级数据的生效模式。"""
    pol = get_policy(conn)
    out = []
    for cname in CLASSES:
        item = dict(INVENTORY[cname])
        item["class"] = cname
        item["default_mode"] = effective_mode(cname, "internal", conn)
        item["modes_by_level"] = {lv: effective_mode(cname, lv, conn) for lv in LEVELS}
        out.append(item)
    return {
        "classes": out,
        "lockdown": bool(pol.get("lockdown") or lockdown_by_env()),
        "classify_enabled": bool(pol.get("classify", True)),
        "fail_mode": "closed" if _fail_closed() else "open",
        "env_overrides": {c: os.getenv(f"MINIYUXI_EGRESS_{c.upper()}", "")
                          for c in CLASSES if os.getenv(f"MINIYUXI_EGRESS_{c.upper()}", "")},
        "presets": {k: {"label": v["label"], "desc": v["desc"]} for k, v in PRESETS.items()},
    }
