#!/usr/bin/env python3
"""打 MiniYuxi 桌面端 sidecar 可执行文件（PyInstaller → Tauri externalBin 所需格式）。

产物：apps/desktop/src-tauri/binaries/miniyuxi-sidecar-<HOST_TRIPLE>[.exe]

⚠️ 命名规则（cargo 实测校准，别写反）：Tauri 把 externalBin 条目名当作前缀、把 target triple
当作**后缀**拼接，即 `<entry>-<triple>`，不是 `<triple>-<entry>`。
  条目 "binaries/miniyuxi-sidecar" + host x86_64-pc-windows-msvc
  → 实际找 `binaries/miniyuxi-sidecar-x86_64-pc-windows-msvc.exe`
写反了 cargo 会报：resource path `binaries/xxx` doesn't exist。

典型用途（仓库根目录）：
    python scripts/build_sidecar.py                       # 用项目 requirements.txt 临时装的 PyInstaller
    python scripts/build_sidecar.py --no-install           # 假设已装 PyInstaller
    python scripts/build_sidecar.py --python "C:\\path\\to\\python.exe"
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENTRY = REPO / "run.py"
WEB = REPO / "web"
SKILLS = REPO / "skills"
DESKTOP_BIN_DIR = REPO / "apps" / "desktop" / "src-tauri" / "binaries"
SIDECAR_NAME = "miniyuxi-sidecar"

# 项目里还有 cli.py（[project.scripts]），避免把 cli 也打进 sidecar（sidecar 只该是内核常驻）
EXTRA_HIDDENIMPORTS = [
    "api",
    "core", "core.agent_loop", "core.tools_registry", "core.security", "core.approval",
    "core.memory", "core.rag", "core.skills_catalog", "core.mcp_client",
    "core.provider_router", "core.scheduler", "core.db", "core.soc_audit",
    "core.taskflow", "core.wb_workbench", "core.experts", "core.model_hub",
    "core.labor_relations", "core.salary_records", "core.hrm", "core.backup",
    "core.multitenant", "core.workbench", "core.coding_agent", "core.channels",
    "core.citation_gate", "core.recruit_dashboard", "core.resume_scorer",
    "core.resume_screening", "core.salary_assist", "core.talent_map",
    "core.interview", "core.connectors", "core.subagent", "core.eval_harness",
    "core.gateway", "core.auth", "core.config", "core.orchestration",
    "core.usage", "core.evolution", "core.canvas",
    "core.rag_adapter", "core.memory_v2",
    "sqlite_vec",  # 向量扩展（注意：它的 vec0.dll 是数据文件，靠 --collect-all 收集）
]

# 一些 helper 模块按需 lazy import：开 collect-all 兜底，宁滥勿缺
# PyInstaller 对动态 from import（如 from core.xxx import yyy）的覆盖较好，
# 这里再补几个被延迟 import 的模块防漏。


def host_target_triple() -> str:
    """当前主机的 Rust target triple（作为产物**后缀**，供 Tauri 按平台打包识别）。"""
    s = platform.system().lower()
    m = platform.machine().lower()
    if s == "windows":
        return "x86_64-pc-windows-msvc" if m in ("amd64", "x86_64") else "i686-pc-windows-msvc"
    if s == "darwin":
        return "aarch64-apple-darwin" if m == "arm64" else "x86_64-apple-darwin"
    if s == "linux":
        return "x86_64-unknown-linux-gnu" if m in ("amd64", "x86_64") else "aarch64-unknown-linux-gnu"
    raise SystemExit(f"未知平台：{s}/{m}")


def ensure_pyinstaller(python: str, install: bool) -> None:
    rc = subprocess.run([python, "-c", "import PyInstaller; print(PyInstaller.__version__)"],
                        capture_output=True, text=True)
    if rc.returncode == 0:
        print(f"  ✓ PyInstaller {rc.stdout.strip()} 已就绪")
        return
    if not install:
        raise SystemExit("未检测到 PyInstaller；请用 --install 或手动 `pip install pyinstaller`")
    print("  · pip install pyinstaller ...")
    subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "pyinstaller"],
                   check=True)


def build(python: str) -> Path:
    ensure_pyinstaller(python, install=True)
    triple = host_target_triple()
    DESKTOP_BIN_DIR.mkdir(parents=True, exist_ok=True)
    # 清掉旧产物（两种写法都清，防止早期写反的残留）
    for pat in (f"*-{SIDECAR_NAME}*", f"{SIDECAR_NAME}-*"):
        for old in DESKTOP_BIN_DIR.glob(pat):
            try: old.unlink()
            except OSError: pass

    exe_suffix = ".exe" if platform.system() == "Windows" else ""
    # Tauri externalBin 规则：<entry>-<target triple>，triple 是后缀
    out_name = f"{SIDECAR_NAME}-{triple}{exe_suffix}"
    out_path = DESKTOP_BIN_DIR / out_name
    if out_path.exists():
        out_path.unlink()

    # data 文件分隔符：Windows `;` / macOS/Linux `:`
    sep = ";" if platform.system() == "Windows" else ":"
    add_data = [
        f"{WEB}{sep}web",              # api.py 启动时要读 web/index.html 等静态文件
        f"{SKILLS}{sep}skills",        # core/skills_catalog.py 从 skills/ 扫 SKILL.md
    ]

    args = [
        python, "-m", "PyInstaller",
        "--clean", "--noconfirm",
        "--onefile",
        "--name", SIDECAR_NAME,
        "--distpath", str(DESKTOP_BIN_DIR / "_work"),
        "--workpath",  str(DESKTOP_BIN_DIR / "_work" / "build"),
        "--specpath",  str(DESKTOP_BIN_DIR / "_work"),
        "--add-data", add_data[0],
    ]
    for m in EXTRA_HIDDENIMPORTS:
        args += ["--hidden-import", m]

    # ⚠️ 关键：sqlite_vec 的 vec0.dll 是「数据文件」不是 .pyd，PyInstaller 默认不收集，
    # 漏了它冻结内核会报 `no such module: vec0` 并直接启动失败。collect-all 才带得上。
    args += ["--collect-all", "sqlite_vec"]

    # 一些兼容性排除项（这些在桌面 sidecar 里用不到，缩小包体）
    args += ["--exclude-module", "tkinter", "--exclude-module", "matplotlib"]

    # entry：直接打 run.py 即可；frozen exe 启动时等价于 `python run.py`，
    # 其 `if __name__ == "__main__": main()` 会按 argv 走 sidecar 分支。
    args.append(str(ENTRY))

    print("  · PyInstaller " + " ".join(args))
    subprocess.run(args, check=True)

    built = DESKTOP_BIN_DIR / "_work" / SIDECAR_NAME / ("miniyuxi-sidecar" + exe_suffix)
    if not built.exists():
        # PyInstaller --onefile 直接把可执行文件放在 distpath 下，不在 _work 子目录里
        built = DESKTOP_BIN_DIR / "_work" / ("miniyuxi-sidecar" + exe_suffix)
    if not built.exists():
        raise SystemExit(f"构建产物未找到：尝试过 {built}")

    shutil.move(str(built), str(out_path))
    # 清理工作目录（_work/ 通常几十~上百 MB）
    shutil.rmtree(DESKTOP_BIN_DIR / "_work", ignore_errors=True)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  ✓ sidecar 已生成：{out_path}（{size_mb:.1f} MB · {triple}）")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable,
                    help="用于 PyInstaller 的解释器（必须与项目依赖一致）")
    ap.add_argument("--no-install", action="store_true",
                    help="不自动 pip install pyinstaller（缺少则报错）")
    args = ap.parse_args()

    if not ENTRY.exists():
        raise SystemExit(f"找不到入口：{ENTRY}")
    if not WEB.exists():
        raise SystemExit(f"找不到 web 目录：{WEB}")

    print("=" * 70)
    print(f"  MiniYuxi sidecar 打包（host = {host_target_triple()}）")
    print("=" * 70)
    try:
        out = build(args.python)
    except subprocess.CalledProcessError as exc:
        print(f"  ✗ PyInstaller 失败：exit={exc.returncode}", file=sys.stderr)
        return 1
    print("-" * 70)
    print(f"  下一步：cd apps/desktop && npm install && npm run build")
    print(f"  Tauri 会自动从 {out.name} 复制到安装包内。")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())