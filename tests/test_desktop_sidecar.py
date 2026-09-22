#!/usr/bin/env python3
"""MiniYuxi 桌面端 sidecar 自检（P3）。

两层覆盖：
  1. 纯单元：core.auth.make_token 的 ttl 自定义参数真的生效（桌面端 7 天 token 的根基）。
  2. 端到端：直接拉起 examples/desktop_tour/code.py 跑 7 步链路
     （可选，未装 fastapi/uvicorn 或传 --unit-only 时跳过）。

跑法：
    python tests/test_desktop_sidecar.py                # 单元 + 端到端
    python tests/test_desktop_sidecar.py --unit-only     # 只跑单元
    MINIYUXI_RUN_INTEGRATION=0 python tests/test_desktop_sidecar.py
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOUR = REPO / "examples" / "desktop_tour" / "code.py"

# 这些依赖在 desktop sidecar 跑通链路时是必需的；任一缺失就降级到只跑单元测试
INTEGRATION_DEPS = ["fastapi", "uvicorn"]


def have_integration_deps() -> bool:
    py = _viable_python()
    if not py:
        return False
    code = "import " + ", ".join(INTEGRATION_DEPS)
    return subprocess.run([py, "-c", code], capture_output=True).returncode == 0


def _viable_python() -> str | None:
    """优先用工作台 .bat 同款解释器，其次退回当前 python。"""
    candidate = Path(r"C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe")
    if candidate.exists():
        return str(candidate)
    return sys.executable


def test_make_token_ttl() -> tuple[bool, str]:
    try:
        sys.path.insert(0, str(REPO))
        from core import auth
    except Exception as exc:                       # noqa: BLE001
        return False, f"import 失败：{exc}"

    # 默认 TTL 走 config.TOKEN_TTL
    t1 = auth.make_token({"tid": "default", "sub": "admin", "role": "admin"})
    b1 = auth.parse_token(t1) or {}
    base_ttl = b1.get("exp", 0) - b1.get("iat", 0)

    # 自定义 TTL = 60s
    t2 = auth.make_token({"tid": "default", "sub": "admin", "role": "admin"}, ttl=60)
    b2 = auth.parse_token(t2) or {}
    custom_ttl = b2.get("exp", 0) - b2.get("iat", 0)

    if not (3000 < base_ttl < 24 * 3600):
        return False, f"默认 TTL 异常：{base_ttl}s"
    if custom_ttl != 60:
        return False, f"自定义 TTL 没生效：{custom_ttl}s（期望 60）"
    return True, f"默认 {base_ttl}s · 自定义 {custom_ttl}s"


def test_tour_end2end(py: str) -> tuple[bool, str]:
    if not TOUR.exists():
        return False, f"找不到 {TOUR}"
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    t0 = time.time()
    proc = subprocess.run([py, str(TOUR)], capture_output=True, text=True, env=env, cwd=str(REPO))
    elapsed = int((time.time() - t0) * 1000)
    if proc.returncode != 0:
        snippet = (proc.stdout + proc.stderr)[-600:]
        return False, f"tour 退出码 {proc.returncode} · {elapsed}ms · 尾巴：{snippet}"
    last_line = [ln for ln in proc.stdout.splitlines() if "通过" in ln]
    if not last_line:
        return False, f"tour 输出缺统计行 · {elapsed}ms"
    return True, f"{last_line[-1].strip()} · {elapsed}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit-only", action="store_true",
                    help="只跑单元（跳过端到端 tour）")
    args = ap.parse_args()

    print("=" * 70)
    print("  MiniYuxi 桌面端 sidecar 自检（P3）")
    print("=" * 70)

    results: list[tuple[str, bool, str]] = []

    ok, msg = test_make_token_ttl()
    results.append(("单元：auth.make_token(ttl=...)", ok, msg))
    print(f"  {'✓' if ok else '✗'} 单元 · {msg}")

    if not args.unit_only:
        if not have_integration_deps():
            print("  · 跳过端到端：fastapi/uvicorn 不可用（pip install -r requirements.txt）")
        elif os.getenv("MINIYUXI_RUN_INTEGRATION") == "0":
            print("  · 跳过端到端：MINIYUXI_RUN_INTEGRATION=0")
        else:
            ok, msg = test_tour_end2end(_viable_python())
            results.append(("端到端：examples/desktop_tour", ok, msg))
            print(f"  {'✓' if ok else '✗'} 端到端 · {msg}")

    passed = sum(1 for _, ok, _ in results if ok)
    print("-" * 70)
    print(f"  {passed}/{len(results)} 通过")
    print("=" * 70)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())