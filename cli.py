#!/usr/bin/env python3
"""MiniYuxi CLI —— 三端统一架构下的 CLI 薄客户端。

设计原则（对齐 docs/三端统一架构与开源增长方案.md）：
  1. CLI 只是「外壳」，业务逻辑全部复用 core/ 内核，与 Web / Desktop 完全一致；
  2. 默认直连内核（import core），不经 HTTP，零网络开销；
  3. 内核延迟导入 —— `--help` / `version` 等不触发冷启动成本；
  4. 任何子命令失败都给可读错误，不抛裸 traceback。

用法：
    miniyuxi chat                 交互式对话（REPL）
    miniyuxi ask "问题"            单次问答
    miniyuxi doctor               环境体检（复用 tests/selftest.py 自检）
    miniyuxi kb list|search|add   知识库
    miniyuxi tools                工具清单
    miniyuxi skills               技能清单
    miniyuxi serve                启动 Web 服务
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DEFAULT_TENANT = os.getenv("MINIYUXI_TENANT", "default")
VERSION = "0.2.0"


def _init_console() -> None:
    """Windows 控制台中文防乱码。"""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            except Exception:
                pass


def _kernel():
    """延迟导入内核。返回 core.rag 模块。"""
    from core import rag  # noqa: PLC0415

    return rag


# ────────────────────────────── 子命令 ──────────────────────────────


def cmd_chat(args: argparse.Namespace) -> int:
    rag = _kernel()
    history: list = []
    print(f"MiniYuxi CLI v{VERSION} · 租户 {args.tenant}")
    print("输入 /exit 退出，/new 清空上下文，/ctx 查看轮次\n")
    while True:
        try:
            q = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见 👋")
            return 0
        if not q:
            continue
        if q in ("/exit", "/quit", "exit", "quit"):
            print("再见 👋")
            return 0
        if q == "/new":
            history.clear()
            print("（上下文已清空）")
            continue
        if q == "/ctx":
            print(f"（当前上下文 {len(history) // 2} 轮）")
            continue

        try:
            r = rag.answer(args.tenant, q, top_k=args.top_k, history=history or None)
        except Exception as exc:  # noqa: BLE001
            print(f"[错误] 内核调用失败：{exc}")
            continue

        ans = (r or {}).get("answer", "") or "(无回答)"
        print(f"\nMiniYuxi> {ans}")

        cits = (r or {}).get("citations") or []
        if cits and not args.no_citations:
            n = min(len(cits), args.max_citations)
            print(f"\n引用（{n}/{len(cits)}）:")
            for i, c in enumerate(cits[:n], 1):
                title = c.get("title", "") if isinstance(c, dict) else str(c)
                print(f"  [{i}] {title}")
        print()

        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": ans})


def _render_answer(r: dict, show_citations: bool = True, max_citations: int = 5) -> None:
    ans = (r or {}).get("answer", "") or "(无回答)"
    print(ans)
    cits = (r or {}).get("citations") or []
    if show_citations and cits:
        n = min(len(cits), max_citations)
        print(f"\n引用（{n}/{len(cits)}）:")
        for i, c in enumerate(cits[:n], 1):
            title = c.get("title", "") if isinstance(c, dict) else str(c)
            print(f"  [{i}] {title}")


def cmd_ask(args: argparse.Namespace) -> int:
    rag = _kernel()
    try:
        r = rag.answer(args.tenant, args.question, top_k=args.top_k)
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 内核调用失败：{exc}")
        return 1
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        _render_answer(r, not args.no_citations, args.max_citations)
    return 0


def _doctor_via_selftest() -> tuple[int, int] | None:
    """复用 tests/selftest.py 的 core_tests()。返回 (通过数, 总数)，不可用时返回 None。"""
    import importlib.util  # noqa: PLC0415

    path = os.path.join(BASE_DIR, "tests", "selftest.py")
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location("_miniyuxi_selftest", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.results.clear()
        mod.core_tests()
        total = len(mod.results)
        ok = sum(1 for _, s, _ in mod.results if s)
        return ok, total
    except Exception as exc:  # noqa: BLE001
        print(f"  [提示] 复用 selftest 失败（{exc}），改用内置基础体检\n")
        return None


def _doctor_builtin() -> tuple[int, int]:
    """不依赖 tests/ 的轻量体检。"""
    checks: list[tuple[str, bool, str]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))

    def warn(name: str, detail: str = "") -> None:
        """告警项：不影响可用性，不计入通过率。"""
        print(f"  [WARN] {name}" + (f"  → {detail}" if detail else ""))

    try:
        from core import db  # noqa: PLC0415

        c = db.connect()
        c.execute("SELECT 1").fetchone()
        chk("SQLite 连接", True, "WAL")

        try:
            v = db.vec_version()
            chk("sqlite-vec 向量扩展", str(v).startswith("v"), str(v))
        except Exception as exc:  # noqa: BLE001
            chk("sqlite-vec 向量扩展", False, str(exc))
    except Exception as exc:  # noqa: BLE001
        chk("SQLite 连接", False, str(exc))

    try:
        from core import rag  # noqa: PLC0415

        hits = rag.search(DEFAULT_TENANT, "劳动合同", top_k=3)
        chk("知识库检索", True, f"命中 {len(hits)} 条")
    except Exception as exc:  # noqa: BLE001
        chk("知识库检索", False, str(exc))

    try:
        from core import tools_registry  # noqa: PLC0415

        tools = tools_registry.list_tools()
        chk("工具注册表", len(tools) > 0, f"{len(tools)} 个工具")
    except Exception as exc:  # noqa: BLE001
        chk("工具注册表", False, str(exc))

    try:
        from core import skills_catalog  # noqa: PLC0415

        skills = skills_catalog.list_skills()
        chk("技能目录", True, f"{len(skills)} 个技能")
    except Exception as exc:  # noqa: BLE001
        chk("技能目录", False, str(exc))

    try:
        from core import config  # noqa: PLC0415

        # LLM 凭证缺失不算失败：项目有离线兜底链路，仅降为告警
        key = os.getenv("LLM_API_KEY") or (config.get("LLM_API_KEY", "") if hasattr(config, "get") else "")
        if key:
            chk("LLM 凭证", True, "已配置")
        else:
            warn("LLM 凭证", "未配置，将走离线兜底（功能仍可用，仅无 LLM 增强）")
    except Exception as exc:  # noqa: BLE001
        chk("LLM 凭证", False, str(exc))

    ok = sum(1 for _, s, _ in checks if s)
    return ok, len(checks)


def cmd_doctor(args: argparse.Namespace) -> int:
    print("=" * 62)
    print(f"  MiniYuxi 环境体检 v{VERSION}")
    print("=" * 62)
    print(f"\n租户：{args.tenant}　内核目录：{BASE_DIR}")

    if args.full:
        print("\n── 完整自检（复用 tests/selftest.py）──")
        res = _doctor_via_selftest()
        ok, total = res if res else _doctor_builtin()
    else:
        print("\n── 基础体检 ──")
        ok, total = _doctor_builtin()

    print("\n" + "=" * 62)
    all_ok = ok == total
    print(f"  结果：{ok}/{total} 通过" + ("　✅ 全部通过" if all_ok else "　❌ 存在失败项"))
    print("=" * 62)
    if not all_ok and not args.full:
        print("\n提示：加 --full 可跑 tests/selftest.py 的完整 20 项自检。")
    return 0 if all_ok else 1


def cmd_kb(args: argparse.Namespace) -> int:
    rag = _kernel()
    if args.kb_cmd == "list":
        docs = rag.list_documents(args.tenant)
        if args.json:
            print(json.dumps(docs, ensure_ascii=False, indent=2))
        else:
            print(f"共 {len(docs)} 篇：")
            for d in docs:
                print(f"  #{d.get('id')}  {d.get('title','')}  （{d.get('n_chunks',0)} 片段）")
        return 0
    if args.kb_cmd == "search":
        hits = rag.search(args.tenant, args.query, top_k=args.top_k)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        else:
            print(f"命中 {len(hits)} 条：")
            for i, h in enumerate(hits, 1):
                print(f"  [{i}] {h.get('title','')}  score={h.get('score',0)}")
        return 0
    if args.kb_cmd == "add":
        if os.path.isfile(args.path):
            text = rag.parse_file(args.path)
            title = args.title or os.path.basename(args.path)
        else:
            text, title = args.path, (args.title or "CLI 录入")
        r = rag.add_document(args.tenant, title, text, source=args.source or "cli")
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else f"已入库：{title}（{r.get('n_chunks',0)} 片段）")
        return 0
    print("未知 kb 子命令")
    return 1


def cmd_tools(args: argparse.Namespace) -> int:
    from core import tools_registry  # noqa: PLC0415

    tools = tools_registry.list_tools()
    if args.json:
        print(json.dumps(tools, ensure_ascii=False, indent=2))
    else:
        print(f"共 {len(tools)} 个工具：")
        for t in tools:
            print(f"  · {t.get('name','')} [{t.get('toolset','')}]  {t.get('description','')[:60]}")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from core import skills_catalog  # noqa: PLC0415

    skills = skills_catalog.list_skills()
    if args.json:
        print(json.dumps(skills, ensure_ascii=False, indent=2))
    else:
        print(f"共 {len(skills)} 个技能：")
        for s in skills:
            name = s.get("name", "") if isinstance(s, dict) else str(s)
            desc = s.get("description", "") if isinstance(s, dict) else ""
            print(f"  · {name}  {desc[:60]}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """启动 Web 服务（等价于 run.py，便于三端统一入口）。"""
    cmd = [sys.executable, os.path.join(BASE_DIR, "run.py")]
    if args.port:
        cmd += ["--port", str(args.port)]
    if args.no_open:
        cmd.append("--no-open")
    print(f"启动 Web 服务：{' '.join(cmd)}")
    return os.execvp(sys.executable, cmd)  # noqa: PLW1510


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"MiniYuxi CLI v{VERSION}")
    print(f"内核目录：{BASE_DIR}")
    print(f"Python   ：{sys.version.split()[0]}")
    return 0


# ────────────────────────────── 参数解析 ──────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="miniyuxi",
        description="MiniYuxi CLI —— 三端统一架构的命令行客户端（复用 core 内核）",
    )
    p.add_argument("--version", action="store_true", help="显示版本")
    sub = p.add_subparsers(dest="cmd")

    # chat
    c = sub.add_parser("chat", help="交互式对话")
    c.add_argument("--tenant", default=DEFAULT_TENANT)
    c.add_argument("--top-k", type=int, default=5)
    c.add_argument("--max-citations", type=int, default=5)
    c.add_argument("--no-citations", action="store_true")
    c.set_defaults(func=cmd_chat)

    # ask
    a = sub.add_parser("ask", help="单次问答")
    a.add_argument("question")
    a.add_argument("--tenant", default=DEFAULT_TENANT)
    a.add_argument("--top-k", type=int, default=5)
    a.add_argument("--max-citations", type=int, default=5)
    a.add_argument("--no-citations", action="store_true")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_ask)

    # doctor
    d = sub.add_parser("doctor", help="环境体检")
    d.add_argument("--tenant", default=DEFAULT_TENANT)
    d.add_argument("--full", action="store_true", help="跑 tests/selftest.py 完整自检")
    d.set_defaults(func=cmd_doctor)

    # kb
    k = sub.add_parser("kb", help="知识库操作")
    ksub = k.add_subparsers(dest="kb_cmd")
    kl = ksub.add_parser("list")
    kl.add_argument("--tenant", default=DEFAULT_TENANT)
    kl.add_argument("--json", action="store_true")
    kl.set_defaults(func=cmd_kb, kb_cmd="list")
    ks = ksub.add_parser("search")
    ks.add_argument("query")
    ks.add_argument("--tenant", default=DEFAULT_TENANT)
    ks.add_argument("--top-k", type=int, default=5)
    ks.add_argument("--json", action="store_true")
    ks.set_defaults(func=cmd_kb, kb_cmd="search")
    ka = ksub.add_parser("add")
    ka.add_argument("path", help="文件路径，或直接给文本")
    ka.add_argument("--title")
    ka.add_argument("--source")
    ka.add_argument("--tenant", default=DEFAULT_TENANT)
    ka.add_argument("--json", action="store_true")
    ka.set_defaults(func=cmd_kb, kb_cmd="add")

    # tools / skills
    t = sub.add_parser("tools", help="工具清单")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_tools)
    s = sub.add_parser("skills", help="技能清单")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_skills)

    # serve
    sv = sub.add_parser("serve", help="启动 Web 服务")
    sv.add_argument("--port", type=int)
    sv.add_argument("--no-open", action="store_true")
    sv.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    _init_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    # 注意顺序：--version 必须先判，否则会被「无子命令→打印 help」抢先
    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0

    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
