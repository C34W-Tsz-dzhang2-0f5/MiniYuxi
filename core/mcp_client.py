"""最小 stdio MCP 客户端（T2）：纯 stdlib 实现 JSON-RPC over stdio，零新增依赖。

用于连接外部 MCP 服务（如 filesystem 只读）。内置一个只读文件 MCP 服务脚本 tools/mcp_readonly_fs.py 作为自证样例。
discover_tools() 懒连接已配置的 MCP 服务，失败则静默返回空（不影响内置工具）。
"""
import json
import subprocess
import threading
from pathlib import Path

from . import tools_registry


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
            "clientInfo": {"name": "miniyuxi", "version": "0.1.0"},
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
