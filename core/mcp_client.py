"""MCP 工具层（T2）：本地 stdio 客户端（内置只读 fs）+ 远程 SSE 客户端（连接 MCP-Adapter 业务总线）。

- 本地 stdio：`MCPClient`（subprocess，连内置 tools/mcp_readonly_fs.py）—— 离线可用，零依赖，向后兼容。
- 远程 SSE：`MCPClientSSE`（JSON-RPC over SSE，连接网络部署的 MCP-Adapter 微服务）。
- `discover_tools()`：本地 fs（向后兼容，离线默认可用）。
- `discover_connector_tools()`：读取 connectors 表中 kind=mcp 的记录，逐个 SSE 连接，拉取工具列表并解析
  `_meta`（risk / confirm_required），经 tools_registry.register 注册（含 risk/requires_approval），
  单一数据源，消除 SKILL.md 双源维护（见 docs/mcp-integration-design-20260928.md）。
- 所有远程 MCP 调用经 core.egress 出境闸门（class=connector）收口（A5）。

⚠️ SSE 客户端用标准库 urllib 实现，适用本地/内网验证与生产；若需更健壮的流式/重连能力，
   后续可替换为官方 mcp 库，但本实现零新增依赖、满足 Option1 MVP 闭环。
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import tools_registry
from .version import __version__ as APP_VERSION


# ---------------- stdio 本地客户端（T2，不变） ----------------
class MCPClient:
    def __init__(self, command):
        self.command = command
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1, encoding="utf-8")
        self._lock = threading.Lock()
        self._id = 0

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        with self._lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _request(self, method, params=None):
        self._id += 1
        mid = self._id
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
        with self._lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    return None
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("id") == mid:
                    return r

    def initialize(self):
        return self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "miniyuxi", "version": APP_VERSION},
        })

    def list_tools(self):
        r = self._request("tools/list", {})
        return (r or {}).get("result", {}).get("tools", [])

    def call_tool(self, name, args=None):
        r = self._request("tools/call", {"name": name, "arguments": args or {}})
        return (r or {}).get("result", {})

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


def _server_cmd():
    root = Path(__file__).resolve().parent.parent
    return ["python", str(root / "tools" / "mcp_readonly_fs.py")]


def discover_tools() -> list:
    """连接内置只读文件 MCP 服务，返回工具元信息并通过 tools_registry 注册（供 /api/tools/list 展示与调用）。"""
    try:
        cli = MCPClient(_server_cmd())
        cli.initialize()
        tools = cli.list_tools()
        cli.close()
        out = []
        for t in tools:
            nm = "mcp." + t.get("name", "?")
            meta = {"name": nm, "description": "[MCP] " + (t.get("description", "")),
                    "schema": t.get("inputSchema", {}), "toolset": "readonly_fs(MCP)"}
            out.append(meta)
            _register_mcp(t, nm)
        return out
    except Exception:
        return []


def _register_mcp(tool_meta, reg_name):
    raw_name = tool_meta.get("name")

    def handler(tenant_id=None, **args):
        try:
            cli = MCPClient(_server_cmd())
            cli.initialize()
            res = cli.call_tool(raw_name, args)
            cli.close()
            return res
        except Exception as e:
            return {"error": str(e)}

    tools_registry.register(
        reg_name,
        "[MCP] " + tool_meta.get("description", ""),
        tool_meta.get("inputSchema", {}),
        "readonly_fs(MCP)",
        handler,
    )


# ---------------- SSE 远程客户端（新增：连接 MCP-Adapter） ----------------
class MCPClientSSE:
    """最小 JSON-RPC over SSE 客户端（MCP 2024-11-05 SSE 传输）。

    握手：GET {base}/sse → 服务端首事件 `endpoint` 给出 POST 地址；
    客户端 POST JSON-RPC 到该地址；响应经 SSE 流以 `message` 事件回传。
    读写分离：单 reader 线程读 SSE 流，主线程发 POST 并按 id 收响应。
    """

    def __init__(self, base_url, token=None, timeout=8.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._lock = threading.Lock()
        self._id = 0
        self._messages = {}            # id -> response dict
        self._cond = threading.Condition()
        self._endpoint = None          # 由 `endpoint` 事件给出的 POST 地址（绝对或相对）
        self._reader = None
        self._stop = False

    # ---- 内部：发请求并等待匹配响应 ----
    def _post(self, method, params):
        with self._lock:
            self._id += 1
            mid = self._id
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
        deadline = time.time() + self.timeout
        with self._cond:
            while self._endpoint is None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("MCP SSE endpoint 未就绪（连接/握手超时）")
                self._cond.wait(remaining)
        body = json.dumps(msg).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self._endpoint, data=body, headers=headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=self.timeout).read()
        except urllib.error.HTTPError as e:
            if e.code >= 400:
                raise
        # 等待响应（SSE 流回传）
        with self._cond:
            while mid not in self._messages:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("MCP SSE 响应超时")
                self._cond.wait(remaining)
            return self._messages.pop(mid)

    def _on_event(self, event, payload):
        if event == "endpoint":
            ep = payload.strip()
            with self._cond:
                self._endpoint = ep if ep.startswith("http") else (self.base_url + ep)
                self._cond.notify_all()
        elif event == "message":
            try:
                msg = json.loads(payload)
            except Exception:
                return
            mid = msg.get("id")
            if mid is None:
                return
            with self._cond:
                self._messages[mid] = msg
                self._cond.notify_all()

    def _reader_loop(self, resp):
        event, data_lines = None, []
        try:
            for raw in resp:
                if self._stop:
                    break
                line = raw.decode("utf-8", "ignore")
                if line.startswith("event:"):
                    event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
                elif line.strip() == "":
                    if event and data_lines:
                        self._on_event(event, "\n".join(data_lines))
                    event, data_lines = None, []
        except Exception:
            pass

    def _connect(self):
        sse_url = self.base_url + "/sse" if not self.base_url.rstrip("/").endswith("/sse") else self.base_url
        headers = {"Accept": "text/event-stream"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(sse_url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        self._reader = threading.Thread(target=self._reader_loop, args=(resp,), daemon=True)
        self._reader.start()

    def initialize(self):
        self._connect()
        return self._post("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "miniyuxi", "version": APP_VERSION},
        })

    def list_tools(self):
        r = self._post("tools/list", {})
        return (r or {}).get("result", {}).get("tools", [])

    def call_tool(self, name, args=None):
        r = self._post("tools/call", {"name": name, "arguments": args or {}})
        return (r or {}).get("result", {})

    def close(self):
        self._stop = True


def _resolve_token(cfg: dict) -> str:
    """从 connector 配置解析 MCP-Adapter 鉴权 token：优先明文 token，否则按 auth.env 取环境变量。"""
    if cfg.get("token"):
        return str(cfg["token"])
    auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else {}
    env = auth.get("env")
    if env:
        return os.getenv(str(env), "")
    return ""


def _make_sse_handler(cid, endpoint, token, raw_name):
    """为某个 mcp 连接器的某个工具生成执行处理器：

    - A5 出境收口：调用前经 core.egress 闸门（class=connector），被拒返回降级文案不崩链路；
    - 实际调用经 SSE 打到 MCP-Adapter（业务底座），MiniYuxi 永不直接持 RuoYi 原始 token。
    """

    def handler(tenant_id=None, **args):
        try:
            from . import egress
            guard = egress.guard("connector", endpoint, args, level="internal", tenant_id=tenant_id)
            if not guard.get("allow", True):
                return {"error": "（MCP 调用被数据出境策略拒绝。请管理员调整「数据出境」策略。）",
                        "egress_decision": guard.get("mode")}
        except Exception:
            pass
        try:
            cli = MCPClientSSE(endpoint, token=token, timeout=10.0)
            cli.initialize()
            res = cli.call_tool(raw_name, args)
            cli.close()
            return res
        except Exception as e:
            return {"error": str(e)}

    return handler


def discover_connector_tools(tenant_id=None) -> list:
    """读取 connectors 表 kind=mcp 的记录，SSE 连接拉取工具并注册（含 _meta）。

    失败（适配器宕机/握手超时/网络隔离）静默返回 []，不影响内置工具与其它连接器——与主链路解耦。
    """
    out = []
    try:
        from . import connectors
        for d in connectors.list_connectors():
            if d.get("kind") != "mcp" or not d.get("enabled"):
                continue
            cfg = json.loads(d.get("config_json") or "{}")
            if cfg.get("transport") != "sse" or not cfg.get("endpoint"):
                continue
            token = _resolve_token(cfg)
            try:
                cli = MCPClientSSE(cfg["endpoint"], token=token, timeout=5.0)
                cli.initialize()
                tools = cli.list_tools()
                cli.close()
            except Exception:
                continue
            for t in tools:
                nm = "mcp." + t.get("name", "?")
                meta = t.get("_meta") or {}
                risk = meta.get("risk", "info")
                confirm = bool(meta.get("confirm_required", False))
                tools_registry.register(
                    nm,
                    "[MCP] " + (t.get("description", "")),
                    t.get("inputSchema", {}),
                    "mcp-adapter",
                    _make_sse_handler(d["id"], cfg["endpoint"], token, t.get("name")),
                    risk=risk,
                    requires_approval=confirm,
                )
                out.append({"name": nm, "description": "[MCP] " + t.get("description", ""),
                            "schema": t.get("inputSchema", {}), "toolset": "mcp-adapter",
                            "risk": risk, "requires_approval": confirm})
    except Exception:
        pass
    return out
