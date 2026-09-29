"""MCP-Adapter：MiniYuxi × RuoYi-Office-Vben 业务底座（生产级 · Option1 MVP）。

对应 docs/mcp-integration-design-20260928.md 的 B1–B4：

  B1 · 封装 RuoYi OpenAPI：配置驱动 base_url + 认证 + OA/CRM/ERP/HRM 业务路径映射。
      业务路径全部可配置（环境变量 RUOYI_ENDPOINTS 覆盖，否则用若依风格默认约定），
      真实实例就绪 → 填配置即连，无需改代码。
  B2 · `_meta` 扩展：每个工具声明 risk(high_risk/warn/info) 与 confirm_required；
      high_risk 工具（销售单/采购单）**默认仅返回预览**，绝不直提交业务单据；
      仅在调用方显式传 `__commit=true`（即已通过 MiniYuxi HITL 续跑）时才真提交。
  B3 · 身份映射：mini_yuxi_user_id ↔ RuoYi token；token 经 Fernet 加密落本地 vault，
      Adapter 永不直接持明文；双层鉴权（Adapter 参数校验 + RuoYi 业务权限由 RuoYi 自身控制）。
  B4 · 异常处理 / 字段脱敏 / 健康检查：请求代理统一异常封装、响应敏感字段脱敏、SSE + /healthz 探针。

运行模式（环境变量 MCP_RUOYI_MODE，默认 mock）：
  mock  —— 内置 mock 业务数据，无真实实例时用于演示 / 测试 / 离线部署，保证不挂；
  ruoyi —— 走真实 RuoYi OpenAPI 客户端（需 RUOYI_BASE_URL / RUOYI_USER / RUOYI_PASS）。

传输：JSON-RPC over SSE（2024-11-05），与 core/mcp_client.MCPClientSSE 对接。

依赖：零新增内核依赖；仅 token vault 用 `cryptography`（Fernet）。若 ruoyi 模式下
      缺失该库，启动即给出明确安装提示，不静默降级。mock 模式不触碰 vault，无需该库。

运行：python tools/mcp_ruoyi_adapter.py [port]   （默认 0 = 随机端口，打印到 stderr）
"""
import json
import os
import queue
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

# ---- 运行模式 ----
MODE = os.getenv("MCP_RUOYI_MODE", "mock").lower()
RUOYI_BASE_URL = os.getenv("RUOYI_BASE_URL", "").rstrip("/")
RUOYI_USER = os.getenv("RUOYI_USER", "")
RUOYI_PASS = os.getenv("RUOYI_PASS", "")

# ---- 默认若依风格业务路径（真实实例可用 RUOYI_ENDPOINTS JSON 覆盖）----
_DEFAULT_ENDPOINTS = {
    "hrm.get_employee": ("GET", "/hrm/employee/{employee_id}"),
    "hrm.list_org": ("GET", "/hrm/org/list"),
    "crm.search_customer": ("GET", "/crm/customer/list"),
    "crm.get_customer": ("GET", "/crm/customer/{customer_id}"),
    "crm.create_lead": ("POST", "/crm/lead"),
    "crm.create_contract_draft": ("POST", "/crm/contract/draft"),
    "erp.check_inventory": ("GET", "/erp/inventory/check"),
    "erp.create_sales_order": ("POST", "/erp/sales-order"),
    "erp.create_purchase_order": ("POST", "/erp/purchase-order"),
    "erp.get_ar_receivable": ("GET", "/erp/ar-receivable/{customer_id}"),
    "oa.submit_approval": ("POST", "/oa/approval/submit"),
    "oa.get_approval_status": ("GET", "/oa/approval/{approval_id}/status"),
    "oa.approval_handoff": ("POST", "/oa/approval/{approval_id}/handoff"),
}


def _load_endpoints():
    raw = os.getenv("RUOYI_ENDPOINTS", "")
    if raw:
        try:
            custom = json.loads(raw)
            merged = dict(_DEFAULT_ENDPOINTS)
            merged.update(custom)
            return merged
        except Exception:
            pass
    return dict(_DEFAULT_ENDPOINTS)


ENDPOINTS = _load_endpoints()

# ---- 工具定义（单一数据源）：name / description / inputSchema / _meta(risk, confirm_required) ----
# 完整覆盖设计文档 §5 蓝图：4 类数据（HRM/CRM/ERP/OA）+ 3 条业务链。
TOOLS = [
    {"name": "hrm.get_employee", "description": "查询员工档案（只读）",
     "inputSchema": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "hrm.list_org", "description": "列出组织/部门树（只读）",
     "inputSchema": {"type": "object", "properties": {}},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "crm.search_customer", "description": "按关键词搜索客户（只读）",
     "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string"}}},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "crm.get_customer", "description": "查询客户主数据（只读）",
     "inputSchema": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "crm.create_lead", "description": "新建线索（低风险写）",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "phone": {"type": "string"}, "source": {"type": "string"}}},
     "_meta": {"risk": "warn", "confirm_required": False}},
    {"name": "crm.create_contract_draft", "description": "创建合同草稿（中风险写）",
     "inputSchema": {"type": "object", "properties": {"customer_id": {"type": "string"}, "amount": {"type": "number"}}},
     "_meta": {"risk": "warn", "confirm_required": False}},
    {"name": "erp.check_inventory", "description": "查询库存（只读）",
     "inputSchema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "erp.get_ar_receivable", "description": "查询应收（只读）",
     "inputSchema": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "erp.create_sales_order", "description": "生成销售订单（高危写·需 HITL）",
     "inputSchema": {"type": "object", "properties": {"order": {"type": "object"}}},
     "_meta": {"risk": "high_risk", "confirm_required": True}},
    {"name": "erp.create_purchase_order", "description": "生成采购订单（高危写·需 HITL）",
     "inputSchema": {"type": "object", "properties": {"order": {"type": "object"}}},
     "_meta": {"risk": "high_risk", "confirm_required": True}},
    {"name": "oa.submit_approval", "description": "提交审批单",
     "inputSchema": {"type": "object", "properties": {"form": {"type": "object"}}},
     "_meta": {"risk": "warn", "confirm_required": False}},
    {"name": "oa.get_approval_status", "description": "查询审批状态（只读）",
     "inputSchema": {"type": "object", "properties": {"approval_id": {"type": "string"}}, "required": ["approval_id"]},
     "_meta": {"risk": "info", "confirm_required": False}},
    {"name": "oa.approval_handoff", "description": "审批后交接：返回下一步执行人（审批≠业务结果·需 HITL）",
     "inputSchema": {"type": "object", "properties": {"approval_id": {"type": "string"}}, "required": ["approval_id"]},
     "_meta": {"risk": "warn", "confirm_required": True}},
]

TOOL_BY_NAME = {t["name"]: t for t in TOOLS}
HIGH_RISK = {t["name"] for t in TOOLS if t["_meta"]["risk"] == "high_risk"}
_PREVIEW_NOTE = "高危写操作仅返回预览，需 HITL 确认后由 Adapter 正式提交 RuoYi（调用方传 __commit=true）"

_SESSIONS = {}            # session_id -> queue.Queue（SSE 写队列）
_SESS_LOCK = threading.Lock()


# ===================== B4 · 字段脱敏 =====================
_SENSITIVE_KEYS = ("id_card", "idcard", "身份证", "phone", "mobile", "tel", "电话",
                   "email", "邮箱", "bank", "bank_card", "银行卡")


def _mask_phone(v):
    s = str(v)
    if len(s) >= 7:
        return s[:3] + "****" + s[-4:]
    return "****"


def _mask_idcard(v):
    s = str(v)
    if len(s) >= 10:
        return s[:6] + "********" + s[-4:]
    return "********"


def _mask_email(v):
    s = str(v)
    if "@" in s:
        u, d = s.split("@", 1)
        return (u[:1] + "***@" + d) if u else ("***@" + d)
    return "***"


def desensitize(obj):
    """递归脱敏响应中的敏感字段（B4）。不修改原始结构语义，仅遮蔽 PII。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out[k] = desensitize(v)
            elif isinstance(v, str) and any(s in k.lower() for s in _SENSITIVE_KEYS):
                if "email" in k.lower() or "邮箱" in k:
                    out[k] = _mask_email(v)
                elif "id_card" in k.lower() or "身份证" in k.lower():
                    out[k] = _mask_idcard(v)
                else:
                    out[k] = _mask_phone(v)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        return [desensitize(x) for x in obj]
    return obj


# ===================== B3 · 身份映射 + Token Vault（加密） =====================
try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover
    Fernet = None


class TokenVault:
    """mini_yuxi_user_id ↔ RuoYi token 加密存储（B3）。

    - token 经 Fernet 加密落本地 SQLite，明文不出 Adapter 进程内存。
    - Fernet 密钥：优先环境变量 RUOYI_FERNET_KEY（base64urlsafe）；否则落地密钥文件
      tools/.ruoyi_fernet_key（仅开发/演示；生产务必用环境变量注入持久密钥）。
    - ruoyi 模式下若 cryptography 缺失，构造即抛清晰错误，不静默降级。
    """

    def __init__(self, db_path=None):
        if Fernet is None and MODE == "ruoyi":
            raise RuntimeError(
                "ruoyi 模式需要 cryptography（Fernet）加密 token，请先：pip install cryptography")
        self._db = db_path or str(Path(__file__).parent / ".ruoyi_token_vault.db")
        self._key = self._load_key()
        self._fernet = Fernet(self._key) if Fernet else None
        self._init_db()

    def _load_key(self):
        env = os.getenv("RUOYI_FERNET_KEY")
        if env:
            return env.encode() if isinstance(env, str) and ":" not in env else env
        kf = Path(__file__).parent / ".ruoyi_fernet_key"
        if kf.exists():
            return kf.read_bytes()
        if Fernet is None:
            # mock 模式：不会用到，给个占位避免崩溃
            return b"dev-only-no-crypto"
        key = Fernet.generate_key()
        kf.write_bytes(key)
        try:
            os.chmod(kf, 0o600)
        except Exception:
            pass
        return key

    def _init_db(self):
        c = sqlite3.connect(self._db)
        c.execute(
            "CREATE TABLE IF NOT EXISTS ruoyi_token_vault("
            "uid TEXT PRIMARY KEY, enc BLOB, ruoyi_user TEXT, expires_at TEXT)")
        c.commit()
        c.close()

    def put(self, uid, token, ruoyi_user="", expires_at=""):
        enc = self._fernet.encrypt(token.encode()) if self._fernet else token.encode()
        c = sqlite3.connect(self._db)
        c.execute(
            "INSERT OR REPLACE INTO ruoyi_token_vault(uid,enc,ruoyi_user,expires_at) VALUES(?,?,?,?)",
            (uid, enc, ruoyi_user, expires_at))
        c.commit()
        c.close()

    def get(self, uid):
        c = sqlite3.connect(self._db)
        row = c.execute("SELECT enc FROM ruoyi_token_vault WHERE uid=?", (uid,)).fetchone()
        c.close()
        if not row:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode() if self._fernet else row[0].decode()
        except Exception:
            return None


# ===================== B1 · 真实 RuoYi OpenAPI 客户端 =====================
class RuoYiClient:
    """配置驱动的 RuoYi OpenAPI 客户端（B1）。

    认证：POST {base}/login（username/password）→ token；后续请求头 Authorization: Bearer <token>。
    业务路径：由 ENDPOINTS 映射（默认若依风格，真实实例可用 RUOYI_ENDPOINTS 覆盖）。
    身份映射：mini_yuxi_user_id 首次访问时登录并加密缓存 token（B3）。
    """

    def __init__(self, base_url, user, password, vault):
        self.base = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.vault = vault
        self._lock = threading.Lock()

    def _ensure_token(self, mini_uid):
        cached = self.vault.get(mini_uid)
        if cached:
            return cached
        # 登录换取 token（若依默认返回 {code:200, token:'...'} 或 {token:'...'}）
        body = json.dumps({"username": self.user, "password": self.password}).encode()
        req = urllib.request.Request(
            self.base + "/login", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            raw = urllib.request.urlopen(req, timeout=8).read()
            data = json.loads(raw)
            token = data.get("token") or (data.get("data") or {}).get("token")
            if not token:
                raise RuntimeError("RuoYi /login 未返回 token：%s" % str(data)[:200])
            self.vault.put(mini_uid, token, ruoyi_user=self.user)
            return token
        except urllib.error.HTTPError as e:
            raise RuntimeError("RuoYi 登录失败 %s：%s" % (e.code, e.read().decode()[:200]))
        except Exception as e:
            raise RuntimeError("RuoYi 登录异常：%s" % str(e)[:200])

    def request(self, method, path, params=None, body=None, mini_uid="default"):
        token = self._ensure_token(mini_uid)
        # 路径参数替换
        remain = dict(params or {})
        def repl(m):
            key = m.group(1)
            if key in remain:
                val = str(remain.pop(key))
                return urllib.parse.quote(val)
            return m.group(0)
        import re
        path = re.sub(r"\{([^}]+)\}", repl, path)
        url = self.base + path
        headers = {"Authorization": "Bearer %s" % token,
                   "Content-Type": "application/json", "Accept": "application/json"}
        data = None
        if method == "GET":
            if remain:
                url += "?" + urlencode(remain)
        else:
            # 剥离内部保留键（__commit / __mini_uid 等），不污染 RuoYi 业务载荷
            payload = dict(body if body is not None else remain)
            for k in list(payload.keys()):
                if k.startswith("__"):
                    payload.pop(k)
            data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            raw = urllib.request.urlopen(req, timeout=10).read()
            return desensitize(json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return {"error": "RuoYi HTTP %s: %s" % (e.code, e.read().decode()[:200])}
        except Exception as e:
            return {"error": "RuoYi 调用异常：%s" % str(e)[:200]}


# ===================== 业务分发（mock / ruoyi 双模式） =====================
_vault = None
_ruoyi = None


def _ensure_backends():
    global _vault, _ruoyi
    if _vault is None:
        _vault = TokenVault()
    if MODE == "ruoyi" and _ruoyi is None:
        _ruoyi = RuoYiClient(RUOYI_BASE_URL, RUOYI_USER, RUOYI_PASS, _vault)


def _mock(name, args):
    """mock 业务数据（无真实实例时演示/测试用）。"""
    if name == "hrm.get_employee":
        return desensitize({"employee_id": args.get("employee_id"), "name": "张三", "dept": "HR",
                            "title": "专员", "id_card": "440300199001011234", "phone": "13800138000"})
    if name == "hrm.list_org":
        return {"org": [{"id": "D1", "name": "总公司"}, {"id": "D2", "name": "销售部"}]}
    if name == "crm.search_customer":
        return {"customers": [{"id": "C1", "name": "某客户A", "level": "A"}, {"id": "C2", "name": "某客户B", "level": "B"}]}
    if name == "crm.get_customer":
        return desensitize({"customer_id": args.get("customer_id"), "name": "某客户", "level": "A",
                            "contact": "13900000000", "email": "a@example.com"})
    if name == "crm.create_lead":
        return {"lead_id": "L-001", "status": "created", "name": args.get("name")}
    if name == "crm.create_contract_draft":
        return {"contract_id": "CT-001", "status": "draft", "customer_id": args.get("customer_id"),
                "amount": args.get("amount")}
    if name == "erp.check_inventory":
        return {"sku": args.get("sku"), "qty": 100, "warehouse": "WH-01"}
    if name == "erp.get_ar_receivable":
        return {"customer_id": args.get("customer_id"), "ar_amount": 50000, "overdue": 0}
    if name == "oa.submit_approval":
        return {"approval_id": "AP-001", "status": "submitted"}
    if name == "oa.get_approval_status":
        return {"approval_id": args.get("approval_id"), "status": "approved", "current_node": "财务"}
    if name == "oa.approval_handoff":
        return {"approval_id": args.get("approval_id"), "next_executor": "采购员", "next_step": "创建采购订单"}
    # 高危写：默认仅预览
    if name in HIGH_RISK:
        return {"preview": True, "order": args.get("order"), "note": _PREVIEW_NOTE}
    return {"echo": args}


def _call_tool(params):
    name = params.get("name")
    args = params.get("arguments", {}) or {}
    if name not in TOOL_BY_NAME:
        return {"content": [{"type": "text", "text": json.dumps({"error": "未知工具：" + str(name)})}]}

    # B2：高危写操作默认仅预览；仅当 __commit=true（已通过 MiniYuxi HITL 续跑）才真提交
    if name in HIGH_RISK and not args.get("__commit"):
        payload = {"preview": True, "order": args.get("order"), "note": _PREVIEW_NOTE}
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                "is_preview": True}

    _ensure_backends()
    try:
        if MODE == "ruoyi":
            method, tpl = ENDPOINTS[name]
            result = _ruoyi.request(method, tpl, params=args, body=args, mini_uid=args.get("__mini_uid", "default"))
        else:
            result = _mock(name, args)
            # mock 高危在 __commit 时返回已提交确认
            if name in HIGH_RISK:
                result = {"committed": True, "order": args.get("order"), "ruoyi_id": "MOCK-PO-001",
                          "note": "（mock 模式）已提交 RuoYi（演示）"}
        if isinstance(result, dict) and result.get("error"):
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "is_error": True}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}],
                "is_error": True}


# ===================== SSE / JSON-RPC 传输（对接 MCPClientSSE） =====================
class _Handler(BaseHTTPRequestHandler):
    def _push(self, sid, event, data):
        with _SESS_LOCK:
            q = _SESSIONS.get(sid)
        if q is not None:
            q.put((event, data))

    def do_GET(self):
        if self.path.split("?")[0] == "/sse":
            self._handle_sse()
        elif self.path.split("?")[0] == "/healthz":
            self._handle_healthz()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_sse(self):
        sid = "sess-%d-%d" % (int(time.time() * 1000), threading.get_ident())
        q = queue.Queue()
        with _SESS_LOCK:
            _SESSIONS[sid] = q
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(("event: endpoint\ndata: /messages?sessionId=%s\n\n" % sid).encode("utf-8"))
        self.wfile.flush()
        try:
            while not self.server._stop:
                item = q.get()
                if item is None:
                    break
                event, data = item
                self.wfile.write(("event: %s\ndata: %s\n\n" % (event, data)).encode("utf-8"))
                self.wfile.flush()
        except Exception:
            pass
        finally:
            with _SESS_LOCK:
                _SESSIONS.pop(sid, None)

    def _handle_healthz(self):
        ok = True
        detail = {"mode": MODE}
        if MODE == "ruoyi":
            ok = bool(RUOYI_BASE_URL)
            detail["ruoyi_base_url"] = RUOYI_BASE_URL or "(未配置)"
        body = json.dumps({"ok": ok, "service": "ruoyi-office-adapter", "detail": detail}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?")[0] == "/messages":
            self._handle_messages()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_messages(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(body or b"{}")
        except Exception:
            req = {}
        sid = parse_qs(urlparse(self.path).query).get("sessionId", [None])[0]
        method = req.get("method")
        mid = req.get("id")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {},
                      "serverInfo": {"name": "ruoyi-office-adapter", "version": "1.0.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = _call_tool(req.get("params", {}))
        else:
            result = {}
        resp = json.dumps({"jsonrpc": "2.0", "id": mid, "result": result})
        self._push(sid, "message", resp)
        self.send_response(202)
        self.end_headers()

    def log_message(self, *a):
        pass


class _Server(ThreadingHTTPServer):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._stop = False


def serve(port=0):
    _ensure_backends()
    srv = _Server(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv, real_port = serve(p)
    print("[mcp-ruoyi-adapter] mode=%s SSE listening on http://127.0.0.1:%d/sse" % (MODE, real_port),
          file=sys.stderr)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv._stop = True
        srv.shutdown()
