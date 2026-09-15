"""Coding Agent（源自李博杰《深入理解 AI Agent》第 5 章核心论点：代码是「能创造新工具的工具」）。

让 MiniYuxi 在运行时由 LLM（或用户直贴代码）生成新工具，并即时注册进 tools_registry，
使该工具立刻可被自主 Agent Loop（agent_loop._to_openai_tools）发现并调用——实现
"Agent 自我扩展能力"的闭环。这是把书中方法论直接落地的功能扩展。

安全边界（对应书中"生产级 Coding Agent 全景"，诚实标注能力边界，详见《企业级合规与架构边界说明》）：
- 生成代码经 AST 静态校验 + 危险调用黑名单，禁止 os/subprocess/eval/exec/open/网络/文件写 等；
- 仅允许白名单模块（json/re/math/datetime/decimal/collections/statistics/random/string）；
- 运行时以受限 __builtins__ 沙箱执行（非 OS 级隔离，仅防常规越权，不应对抗性攻防）；
- 工具名白名单 + 不与内置工具冲突；持久化到 generated_tools 表，重启可恢复。
"""
import ast
import re
import uuid

from . import db, tools_registry, config

_ALLOWED_IMPORTS = {
    "json", "re", "math", "datetime", "decimal", "collections",
    "statistics", "random", "string",
}
# 危险名字/属性，命中即拒绝（函数名、属性名、调用名）
_FORBIDDEN = {
    "eval", "exec", "compile", "open", "os", "sys", "subprocess", "shutil",
    "socket", "pickle", "marshal", "importlib", "ctypes", "__import__",
    "getattr", "setattr", "globals", "locals", "vars", "input", "exit", "quit",
    "breakpoint", "requests", "urllib", "http", "ftplib", "smtplib",
    "telnetlib", "codeop", "socket",
}
# 内置工具名，禁止覆盖
_RESERVED = {"current_time", "calc", "kb_search", "count_docs", "web_search"}

_GEN_TOOLSET = "generated"

# 受限运行环境：仅暴露安全内置（沙箱门禁：阻断危险模块/调用，但不限制无害的字符串/数值辅助函数）
_SAFE_BUILTINS = {
    "len": len, "range": range, "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "sorted": sorted, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "print": print, "isinstance": isinstance,
    "chr": chr, "ord": ord, "repr": repr, "format": format, "all": all, "any": any,
    "pow": pow, "divmod": divmod, "frozenset": frozenset, "bytes": bytes,
    "bytearray": bytearray, "hash": hash,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "ZeroDivisionError": ZeroDivisionError,
    "True": True, "False": False, "None": None,
}
_SAFE_MODULES = {m: __import__(m) for m in _ALLOWED_IMPORTS}


def _name_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name or "")) and name not in _RESERVED


def validate_tool_code(code: str) -> tuple[bool, str, str | None]:
    """静态校验生成代码。返回 (ok, 错误说明, 提取到的函数名)。

    要求：恰好一个函数定义且名为 run；仅白名单 import；无危险调用/属性；返回 dict 或 str。
    """
    if not code or not code.strip():
        return False, "代码为空", None
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误：{e}", None

    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in _ALLOWED_IMPORTS:
                    return False, f"禁止导入模块：{a.name}", None
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] not in _ALLOWED_IMPORTS:
                return False, f"禁止导入模块：{node.module}", None
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN:
            return False, f"禁止使用的标识符：{node.id}", None
        if isinstance(node, ast.Attribute) and (node.attr in _FORBIDDEN or node.attr.startswith("__")):
            return False, f"禁止访问的属性：{node.attr}", None
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _FORBIDDEN:
                return False, f"禁止调用：{fn.id}()", None
            if isinstance(fn, ast.Attribute) and (fn.attr in _FORBIDDEN or fn.attr.startswith("__")):
                return False, f"禁止调用：.{fn.attr}()", None
        if isinstance(node, ast.FunctionDef):
            func = node

    if func is None:
        return False, "未找到函数定义（需定义名为 run 的函数）", None
    if func.name != "run":
        return False, f"函数名必须为 run，当前为 {func.name}", None
    return True, "", "run"


def _compile_handler(code: str):
    """把代码编译为可调用 handler(tenant_id=None, **kwargs) -> dict|str。"""
    ns = {"__builtins__": _SAFE_BUILTINS}
    ns.update(_SAFE_MODULES)
    exec(compile(code, "<generated_tool>", "exec"), ns)
    run_fn = ns.get("run")
    if not callable(run_fn):
        raise ValueError("编译后未找到可调用 run 函数")

    def handler(tenant_id=None, **kwargs):
        try:
            res = run_fn(tenant_id=tenant_id, **kwargs)
        except TypeError:
            res = run_fn(**kwargs)
        if isinstance(res, dict):
            return res
        return {"result": str(res)}

    return handler


def install_tool(tenant_id: str, name: str, description: str, code: str) -> dict:
    """校验 → 编译 → 注册进 tools_registry → 持久化（重启可恢复）。"""
    ok, err, _ = validate_tool_code(code)
    if not ok:
        return {"ok": False, "error": err}
    if not _name_ok(name):
        return {"ok": False, "error": f"工具名非法或冲突：{name}（须 ^[a-z][a-z0-9_]{{1,30}}$，且不与内置工具重名）"}
    try:
        handler = _compile_handler(code)
    except Exception as e:
        return {"ok": False, "error": f"编译失败：{e}"}

    tools_registry.register(name, description, {"type": "object", "properties": {}}, _GEN_TOOLSET, handler)

    conn = db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO generated_tools(name,tenant_id,description,code,created_at) "
        "VALUES(?,?,?,?,datetime('now'))",
        (name, tenant_id, description, code),
    )
    conn.commit()
    return {"ok": True, "name": name, "toolset": _GEN_TOOLSET}


def remove_tool(tenant_id: str, name: str) -> dict:
    """从注册表与持久化表中移除自生成工具。"""
    tools_registry.unregister(name)
    conn = db.connect()
    conn.execute("DELETE FROM generated_tools WHERE tenant_id=? AND name=?", (tenant_id, name))
    conn.commit()
    return {"ok": True, "removed": name}


def list_generated(tenant_id: str) -> list[dict]:
    rows = db.connect().execute(
        "SELECT name,tenant_id,description,created_at FROM generated_tools WHERE tenant_id=? ORDER BY created_at DESC",
        (tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_blueprint() -> dict:
    """返回离线（无 LLM）模板示例，供前端直接展示/复用。"""
    return {
        "name": "gen_textstat",
        "description": "统计输入文本的字符数、词数、行数",
        "code": "def run(tenant_id=None, **kwargs):\n"
                "    t = kwargs.get('text', '') or ''\n"
                "    return {'result': f'字符数={len(t)} 词数={len(t.split())} 行数={t.count(chr(10))+1}'}",
    }


def generate_tool(tenant_id: str, description: str, code: str = None, name: str = None) -> dict:
    """自生成工具：给定自然语言描述，由 LLM 产出工具代码并注册；或直接用用户提供的 code。

    - code 非空：跳过 LLM，直接安装（离线/模板模式）。
    - code 为空且配置了 LLM：调用网关生成代码（带严格约束与示例）。
    - code 为空且无 LLM：返回模板示例与指引，不静默失败。
    """
    if not name:
        name = "gen_" + uuid.uuid4().hex[:8]

    if code and code.strip():
        return install_tool(tenant_id, name, description, code.strip())

    if not config.llm_enabled():
        return {
            "ok": False,
            "mode": "offline-no-code",
            "hint": "当前未配置 LLM_API_KEY，无法自动生成代码。请在下方直接粘贴符合规范的工具代码，"
                    "或配置 LLM_API_KEY 后重试。可参考蓝图示例。",
            "blueprint": get_blueprint(),
        }

    prompt = (
        "你是一个 Coding Agent。请根据用户需求，编写一个 Python 工具函数。\n"
        "严格要求：\n"
        "1. 只定义一个函数：def run(tenant_id=None, **kwargs):\n"
        "2. 函数必须返回一个 dict，且包含字符串键 'result'（如 return {'result': '...'}）。\n"
        "3. 仅允许导入模块：json, re, math, datetime, decimal, collections, statistics, random, string。\n"
        "4. 禁止使用 eval/exec/open/os/sys/subprocess/网络/文件写/__import__ 等危险操作。\n"
        "5. 只输出 ```python 代码块，不要任何解释。\n\n"
        "示例：\n"
        "```python\n"
        "import math\n"
        "def run(tenant_id=None, **kwargs):\n"
        "    a = float(kwargs.get('a', 0)); b = float(kwargs.get('b', 0))\n"
        "    return {'result': f'{a} 与 {b} 的平方和={a*a + b*b}'}\n"
        "```\n\n"
        f"用户需求：{description}\n"
    )
    try:
        from . import gateway

        res = gateway.chat("你是严谨的 Coding Agent，只输出代码。", prompt, tenant_id=tenant_id)
    except Exception as e:  # noqa
        return {"ok": False, "error": f"LLM 调用失败：{e}"}
    if not res.get("ok"):
        return {"ok": False, "error": f"LLM 生成失败：{res.get('err')}"}
    code = _extract_code(res.get("text", ""))
    if not code:
        return {"ok": False, "error": "LLM 未返回可解析的 python 代码块"}
    return install_tool(tenant_id, name, description, code)


def _extract_code(text: str) -> str | None:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return m.group(1).strip() if m else None


def init(conn=None) -> None:
    """运行时建表 + 重载持久化工具（重启恢复）。失败不阻塞主链路。"""
    try:
        c = conn or db.connect()
        c.execute(
            """CREATE TABLE IF NOT EXISTS generated_tools(
                name TEXT, tenant_id TEXT, description TEXT, code TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(name, tenant_id))"""
        )
        c.commit()
        # 重载：把持久化的工具重新编译并注册（全局可用，与内置工具同生命周期）
        for row in c.execute(
            "SELECT name,tenant_id,description,code FROM generated_tools"
        ).fetchall():
            try:
                handler = _compile_handler(row["code"])
                tools_registry.register(
                    row["name"], row["description"],
                    {"type": "object", "properties": {}}, _GEN_TOOLSET, handler
                )
            except Exception:  # noqa
                pass
    except Exception:  # noqa
        pass
