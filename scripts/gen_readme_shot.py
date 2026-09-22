#!/usr/bin/env python3
"""生成 README 首屏截图（落地页"视觉锤"）。

做法与桌面外壳完全一致（顺带当作外壳行为的可视化验证）：
    拉起 sidecar 内核 → 等 READY 契约 → 注入 token → 打开 http://127.0.0.1:<port> → 截图

用法：
    python scripts/gen_readme_shot.py                       # 默认 1440x900，输出 docs/_shots/readme_hero.png
    python scripts/gen_readme_shot.py --port 8801 --full    # --full 截整页
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
READY_PREFIX = "MINIYUXI_SIDECAR_READY "
DEFAULT_OUT = REPO / "docs" / "assets" / "readme_hero.png"


def start_sidecar(port: int) -> tuple[subprocess.Popen, dict]:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "run.py"), "--sidecar", "--port", str(port)],
        cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    info = None
    deadline = time.time() + 120
    while time.time() < deadline:
        line = proc.stdout.readline()          # type: ignore[union-attr]
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"sidecar 提前退出：{(proc.stderr.read() or '')[-500:]}")  # type: ignore[union-attr]
            continue
        if line.startswith(READY_PREFIX):
            info = json.loads(line[len(READY_PREFIX):].strip())
            break
    if not info:
        proc.terminate()
        raise RuntimeError("未收到 READY 契约行")
    return proc, info


def shutdown(proc: subprocess.Popen, info: dict) -> None:
    try:
        req = urllib.request.Request(
            f"{info['url']}/api/desktop/shutdown", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {info['token']}"})
        urllib.request.urlopen(req, timeout=10).read()
        proc.wait(timeout=20)
    except Exception:
        proc.terminate()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("MINIYUXI_PORT", "8801")))
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--full", action="store_true", help="截整页（默认只截首屏）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要 playwright：pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    print("· 拉起 sidecar 内核 …")
    proc, info = start_sidecar(args.port)
    print(f"  ✓ {info['url']}（端口 {info['port']}）")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": args.width, "height": args.height})
            # 与桌面外壳 initialization_script 等价：先落 token，再访问
            page.add_init_script(
                "try{localStorage.setItem('miniyuxi_token', %s);"
                "localStorage.setItem('miniyuxi_role', %s);"
                "localStorage.setItem('miniyuxi_tenant', %s);}catch(e){}"
                % (json.dumps(info["token"]), json.dumps(info["role"]), json.dumps(info["tenant"]))
            )
            page.goto(info["url"] + "/", wait_until="domcontentloaded")
            # 工作台是异步渲染的，等到有实质内容再截（最长 15s）
            try:
                page.wait_for_function(
                    "() => document.body && document.body.innerText.trim().length > 200",
                    timeout=15000)
            except Exception:
                print("  ⚠ 页面内容偏少，仍按当前状态截图")
            page.wait_for_timeout(2500)   # 给图表/侧栏动画收尾
            page.screenshot(path=str(out), full_page=args.full)
            title = page.title()
            browser.close()
    finally:
        print("· 关闭内核 …")
        shutdown(proc, info)

    size_kb = out.stat().st_size / 1024
    print(f"  ✓ 截图已生成：{out}（{size_kb:.0f} KB · {args.width}x{args.height} · title={title}）")
    print(f"    README 引用写法：![MiniYuxi 三端统一工作台]({out.relative_to(REPO).as_posix()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
