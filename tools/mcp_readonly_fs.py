"""最小只读文件 MCP 服务（stdio JSON-RPC）。仅供 MiniYuxi 自证 MCP 链路；只允许读 sandbox 目录。

运行方式：由 core/mcp_client.py 以子进程方式启动，通过 stdin/stdout 交换 JSON-RPC。
零第三方依赖，仅使用 Python 标准库。
"""
import json
import os
import pathlib
import sys

SANDBOX = pathlib.Path(__file__).resolve().parent.parent / "data"

TOOLS = [{
    "name": "read_file",
    "description": "读取 sandbox 目录内的文本文件（只读，禁止越权路径）",
    "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
}]


def read_file(path: str):
    try:
        p = (SANDBOX / path).resolve()
        if str(p) != str(SANDBOX / path) and not str(p).startswith(str(SANDBOX.resolve())):
            return {"content": [{"type": "text", "text": "拒绝：越权路径"}], "isError": True}
        if not p.exists():
            return {"content": [{"type": "text", "text": "文件不存在"}], "isError": True}
        text = p.read_text(encoding="utf-8", errors="ignore")[:2000]
        return {"content": [{"type": "text", "text": text}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"读取失败：{e}"}], "isError": True}


def _respond(mid, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            _respond(mid, {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "readonly_fs", "version": "1.0.0"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _respond(mid, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            if name == "read_file":
                _respond(mid, read_file(args.get("path", "")))
            else:
                _respond(mid, {"content": [{"type": "text", "text": "未知工具"}], "isError": True})
        else:
            _respond(mid, {})


if __name__ == "__main__":
    main()
