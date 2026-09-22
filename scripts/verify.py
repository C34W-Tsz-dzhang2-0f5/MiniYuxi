#!/usr/bin/env python3
"""MiniYuxi 一键质量闸门（本地与 CI 同构）。

背景：`docs/三端统一架构与开源增长方案.md` §6 要求
「`scripts/verify.py` + Actions 绿，selftest 20/20 作为质量凭证展示」。
此前只有 bash 版 `scripts/verify-precommit.sh`（Windows 上跑不顺），
CI 又散着拼多条命令 —— 本脚本把 CI 的每一步收敛成单一入口，
本地一条命令就能复现 CI 结果，不用等 push 才发现问题。

跑法：
    python scripts/verify.py              # 全量（等价 CI）
    python scripts/verify.py --quick       # 只跑纯 stdlib 快卡点
    python scripts/verify.py --json        # 机器可读输出（给 CI/脚本用）

退出码：0 = 所有必跑卡点通过；1 = 有必跑卡点失败。
依赖缺失的卡点标 SKIP（不阻断），与 CI 的「装好依赖再跑」语义一致。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _has(*mods: str) -> bool:
    code = "import " + ", ".join(mods)
    return subprocess.run([PY, "-c", code], capture_output=True).returncode == 0


# (名称, 命令, 需要的依赖, 是否属于 quick 子集)
STEPS: list[tuple[str, list[str], tuple[str, ...], bool]] = [
    ("未定义符号扫描（前端回归）",
     [PY, "tests/_scan_undef.py"], (), True),
    ("引用闸门单测（法务无引用不出文）",
     [PY, "tests/_verify_citation_gate.py"], (), True),
    ("桌面端 sidecar 单元（token ttl）",
     [PY, "tests/test_desktop_sidecar.py", "--unit-only"], (), True),
    ("路由冒烟（前端验收）",
     [PY, "tests/_smoke_routes.py"], ("fastapi", "httpx"), False),
    ("内核自检（selftest 20/20）",
     [PY, "tests/selftest.py"], ("fastapi", "httpx"), False),
    ("Hermes 落地页",
     [PY, "-m", "pytest", "tests/test_hermes_landing.py", "-q"],
     ("pytest", "fastapi", "httpx"), False),
    ("性能优化回归",
     [PY, "-m", "pytest", "tests/test_perf_optimizations.py", "-q"],
     ("pytest", "fastapi", "httpx"), False),
]


def run_steps(quick: bool) -> tuple[list[dict], int]:
    results: list[dict] = []
    for name, cmd, deps, is_quick in STEPS:
        if quick and not is_quick:
            continue
        if deps and not _has(*deps):
            results.append({"name": name, "status": SKIP,
                            "detail": f"缺依赖：{'/'.join(deps)}", "ms": 0})
            print(f"  [{SKIP}] {name}  → 缺依赖 {'/'.join(deps)}（CI 会装好再跑）")
            continue
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        ms = int((time.time() - t0) * 1000)
        ok = proc.returncode == 0
        # 末行常是 ==== / ---- 分隔线，过滤掉再取，否则汇总看不出结果
        tail = [ln.strip() for ln in (proc.stdout + proc.stderr).splitlines()]
        tail = [ln for ln in tail if ln and set(ln) not in ({"="}, {"-"})]
        detail = tail[-1][:160] if tail else f"exit {proc.returncode}"
        results.append({"name": name, "status": PASS if ok else FAIL,
                        "detail": detail, "ms": ms})
        print(f"  [{'✓' if ok else '✗'}] {name}  → {detail}" + (f" · {ms}ms" if ms else ""))
    failed = sum(1 for r in results if r["status"] == FAIL)
    return results, failed


def main() -> int:
    ap = argparse.ArgumentParser(description="MiniYuxi 一键质量闸门")
    ap.add_argument("--quick", action="store_true", help="只跑纯 stdlib 快卡点")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    quiet = args.json
    if not quiet:
        print("=" * 70)
        print("  MiniYuxi 质量闸门" + ("（quick）" if args.quick else "（全量，等价 CI）"))
        print("=" * 70)

    results, failed = run_steps(args.quick)

    if args.json:
        print(json.dumps({"failed": failed, "results": results}, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    passed = sum(1 for r in results if r["status"] == PASS)
    skipped = sum(1 for r in results if r["status"] == SKIP)
    print("-" * 70)
    print(f"  通过 {passed} · 失败 {failed} · 跳过 {skipped}")
    print("  " + ("✓ 闸门全绿" if failed == 0 else "✗ 有卡点未过，禁止提交/合并"))
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
