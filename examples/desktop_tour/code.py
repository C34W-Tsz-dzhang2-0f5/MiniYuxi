#!/usr/bin/env python3
"""桌面端离线贯通演示（P3）——不装 Rust / Node 也能验证「桌面六层」链路。

它把 apps/desktop（Tauri 外壳）真正要做的事完整跑一遍，只是把 Rust 换成 Python：

    Desktop UI (外壳)             ← 本脚本扮演
       ↓ 拉起 sidecar + 读 READY 契约
    Local App Server (api.py)     ← 现有内核，sidecar 常驻
       ↓
    Session/Token → Agent Loop → core/（工具 / 记忆 / RAG / 技能 / 审计）

跑法（仓库根目录）：
    python examples/desktop_tour/code.py          # 默认端口 8801（被占则自动顺延）
    python examples/desktop_tour/code.py --port 8901
    python examples/desktop_tour/code.py --keep   # 跑完不关 sidecar，方便手动看 UI

判定标准：全部步骤 ✓ 且退出码 0。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# 非打包时就是仓库 data/；打包后由 MINIYUXI_DATA_DIR 指向用户目录（见 run.py::_frozen_bootstrap）
DATA_DIR = os.getenv("MINIYUXI_DATA_DIR") or os.path.join(BASE_DIR, "data")
READY_PREFIX = "MINIYUXI_SIDECAR_READY "
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

rows: list[dict] = []
_sidecar: dict = {}


def step(name: str) -> callable:
    """步骤装饰器：记录耗时与成败，失败即抛（后续步骤跳过）。"""

    def deco(fn):
        def wrapper(*a, **kw):
            t0 = time.time()
            try:
                detail = fn(*a, **kw) or ""
                rows.append({"step": name, "ok": True, "detail": str(detail)[:110],
                             "ms": int((time.time() - t0) * 1000)})
                print(f"  ✓ {name}  （{rows[-1]['ms']}ms）")
                return detail
            except Exception as exc:  # noqa: BLE001
                rows.append({"step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:110],
                             "ms": int((time.time() - t0) * 1000)})
                print(f"  ✗ {name}  → {exc}")
                raise
        return wrapper
    return deco


def frozen_data_dir() -> str:
    """与 run.py::_frozen_bootstrap 保持一致的冻结态数据目录（--exe 模式下 sidecar.json 落在这里）。"""
    if sys.platform == "win32":
        root = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, "MiniYuxi", "data")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "MiniYuxi", "data")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "miniyuxi")


def _http(method: str, path: str, body: dict | None = None, token: str = "", timeout: float = 30.0):
    url = f"{_sidecar['url']}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


@step("1. 拉起 sidecar 内核（run.py --sidecar）")
def spawn(port: int, exe: str = "") -> str:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["MINIYUXI_SIDECAR_WATCH_STDIN"] = "1"   # 演示 stdin 看门狗：本脚本退出即带走 sidecar
    if exe:
        # 冻结内核（PyInstaller 产物）：验证「打包后仍然跑同一套契约」
        cmd = [exe, "--sidecar", "--port", str(port)]
    else:
        cmd = [sys.executable, os.path.join(BASE_DIR, "run.py"), "--sidecar", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, cwd=BASE_DIR, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    _sidecar["proc"] = proc
    print(f"     命令：{' '.join(cmd)}")
    return f"pid={proc.pid}"


@step("2. 等 READY 契约行（stdout / data/sidecar.json 双通道）")
def wait_ready(timeout: int = 120) -> str:
    proc = _sidecar["proc"]
    deadline = time.time() + timeout
    payload = None

    def _read_stdout() -> None:
        nonlocal payload
        try:
            for line in proc.stdout:                 # type: ignore[union-attr]
                if line.startswith(READY_PREFIX):
                    payload = json.loads(line[len(READY_PREFIX):].strip())
                    return
        except Exception:
            return

    t = threading.Thread(target=_read_stdout, daemon=True)
    t.start()

    # 渠道 B 兜底：sidecar 一启动就写 data/sidecar.json（防止 stdout 被缓冲吞掉）
    info_path = os.path.join(DATA_DIR, "sidecar.json")
    while time.time() < deadline and not payload:
        if proc.poll() is not None:
            err = ""
            try:
                err = (proc.stderr.read() or "")[-600:]      # type: ignore[union-attr]
            except Exception:
                pass
            raise RuntimeError(f"sidecar 提前退出（code={proc.returncode}）{err}")
        if os.path.isfile(info_path):
            try:
                with open(info_path, encoding="utf-8") as f:
                    file_info = json.load(f)
                if file_info.get("port"):
                    _sidecar.setdefault("file_info", file_info)
            except Exception:
                pass
        time.sleep(0.2)
    t.join(timeout=10)

    if not payload:                                   # stdout 没抓到 → 用文件兜底
        payload = _sidecar.get("file_info")
    if not payload:
        raise RuntimeError(f"{timeout}s 内未收到 MINIYUXI_SIDECAR_READY")
    if not payload.get("ok", True):
        raise RuntimeError("READY 中 ok=false（health 探针未通过）")

    _sidecar.update(payload)
    _sidecar["url"] = payload["url"]
    return f"port={payload['port']} · token 已签发（{payload['user']}@{payload['tenant']}）"


@step("3. GET /api/health（外壳的探活口）")
def health() -> str:
    d = _http("GET", "/api/health")
    return f"{d['service']} v{d['version']} · llm={d['modes']['llm']} · vec={d['storage']['vector']}"


@step("4. GET /api/me（sidecar token 可用）")
def me() -> str:
    d = _http("GET", "/api/me", token=_sidecar["token"])
    return f"{d['user']}@{d['tenant']} role={d['role']} 权限 {len(d['perms'])} 项"


@step("5. POST /api/chat（内核离线兜底问答，无需 LLM Key）")
def chat() -> str:
    d = _http("POST", "/api/chat", {"question": "MiniYuxi 是什么？一句话说明。", "top_k": 3},
              token=_sidecar["token"], timeout=90)
    ans = (d.get("answer") or d.get("text") or "").replace("\n", " ")
    if not ans:
        raise RuntimeError(f"空回复：{str(d)[:120]}")
    return f"{ans[:90]}"


@step("6. GET /api/tools/list（工具注册表对外壳一致可见）")
def tools() -> str:
    d = _http("GET", "/api/tools/list", token=_sidecar["token"])
    items = d if isinstance(d, list) else d.get("tools", d.get("items", []))
    return f"{len(items)} 个工具"


@step("7. 优雅关闭（POST /api/desktop/shutdown → 不留孤儿进程）")
def shutdown(keep: bool) -> str:
    proc = _sidecar["proc"]
    if keep:
        return f"--keep：sidecar 保持运行 → {_sidecar['url']}"
    try:
        _http("POST", "/api/desktop/shutdown", {}, token=_sidecar["token"], timeout=10)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"停机接口返回 {exc.code}（需管理员 token）")
    try:
        code = proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.terminate()
        code = proc.wait(timeout=10)
        return f"HTTP 停机超时 → 已回退 terminate（exit={code}）"
    gone = not os.path.isfile(os.path.join(DATA_DIR, "sidecar.json"))
    return f"exit={code} · data/sidecar.json 已清理={gone}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("MINIYUXI_PORT", "8801")))
    ap.add_argument("--keep", action="store_true", help="跑完保留 sidecar（可手动打开 UI 看效果）")
    ap.add_argument("--exe", default="",
                    help="用打包后的 sidecar 可执行文件跑（验证冻结内核同样遵守 READY 契约）")
    args = ap.parse_args()

    global DATA_DIR
    if args.exe and not os.getenv("MINIYUXI_DATA_DIR"):
        DATA_DIR = frozen_data_dir()   # 冻结内核的 sidecar.json 在用户目录，不在仓库 data/

    print("=" * 74)
    print("  MiniYuxi 桌面端离线贯通演示（外壳 → sidecar → api.py → core/）")
    if args.exe:
        print(f"  模式：冻结内核（PyInstaller 产物）· 数据目录 {DATA_DIR}")
    print("=" * 74)
    ok = True
    try:
        spawn(args.port, args.exe)
        wait_ready()
        health()
        me()
        chat()
        tools()
        shutdown(args.keep)
    except Exception:
        ok = False
    finally:
        proc = _sidecar.get("proc")
        if proc and proc.poll() is None and not args.keep:
            proc.terminate()

    print("-" * 74)
    passed = sum(1 for r in rows if r["ok"])
    for r in rows:
        flag = "✓" if r["ok"] else "✗"
        print(f"  {flag} {r['step']:<46} {r['ms']:>5}ms  {r['detail']}")
    print("-" * 74)
    print(f"  {passed}/{len(rows)} 步通过 · 耗时合计 {sum(r['ms'] for r in rows)}ms")
    if args.keep:
        print(f"  sidecar 仍在运行：{_sidecar.get('url', '')}  （Ctrl+C 或关闭本窗口即退出）")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
