# -*- coding: utf-8 -*-
"""冻结产物内容校验：确认 exe 里装的就是我这次改的东西。

不需要起服务、不需要浏览器 —— 直接读 exe 的内部归档。

⚠️ 关于「字节级证明」的边界（别误解这个脚本能证明什么）：
  - **数据文件**（web/*.js、*.html、skills/ 等）是原样打包的 → 可以做 md5 逐字节比对。
  - **Python 模块**编译进 `PYZ.pyz`（存的是 `.pyc`，**源码不打包**）→ 无法与 .py 做
    字节比对，只能证明「模块存在于 PYZ 中」。真正的行为证明是起 exe 打 /api/health
    与 /api/egress/* 看返回（见 tests/_verify_egress_api.py 的装机版跑法）。

用法：
    .venv/Scripts/python.exe scripts/verify_sidecar_contents.py [exe路径]
    .venv/Scripts/python.exe scripts/verify_sidecar_contents.py "C:/Program Files/MiniYuxi/binaries/miniyuxi-sidecar.exe"
"""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EXE = os.path.join(
    ROOT, "apps", "desktop", "src-tauri", "binaries",
    "miniyuxi-sidecar-x86_64-pc-windows-msvc.exe")

# 必须存在于 PYZ 的 Python 模块（本次改动涉及）
WANT_MODULES = [
    "api", "run",
    "core.egress", "core.version", "core.gateway", "core.tools_registry",
    "core.rag", "core.rag_adapter", "core.connectors", "core.model_hub",
    "core.provider_router", "core.office", "core.soc_audit", "core.approval",
]
# 必须存在且可与源码逐字节比对的数据文件
WANT_DATA = [
    "web/wb_workbench.js",
    "web/index.html",
    "web/office/office-host.js",
    "web/vendor/univer/univer.worker.js",
]


def norm(k: str) -> str:
    return k.replace("\\", "/")


def main() -> int:
    from PyInstaller.archive.readers import CArchiveReader

    exe = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXE
    if not os.path.exists(exe):
        print(f"找不到 exe：{exe}")
        return 2
    raw = open(exe, "rb").read()
    print("=" * 76)
    print("冻结产物内容校验")
    print(f"  {exe}")
    print(f"  size={len(raw) / 1024 / 1024:.1f} MB   md5={hashlib.md5(raw).hexdigest()}")
    print("=" * 76)

    r = CArchiveReader(exe)
    keys = list(r.toc.keys())

    # ---- 1) Python 模块：查 PYZ ----
    #  注意：**入口脚本（run）不进 PYZ**，它作为脚本条目存在 CArchive 顶层 TOC 里，
    #  所以下面两个归档都要查，否则会误报 run 缺失。
    print("\n[1] Python 模块（编译进 PYZ.pyz，只能验证存在性）")
    pyz = None
    try:
        pyz = r.open_embedded_archive("PYZ.pyz")
        mods = set(pyz.toc.keys())
    except Exception as exc:
        print(f"  !! 无法打开 PYZ：{exc}")
        mods = set()
    top = set(norm(k) for k in keys)
    bad = 0
    for m in WANT_MODULES:
        ok = (m in mods) or (m in top)
        if not ok:
            bad += 1
        where = "PYZ" if m in mods else ("CArchive" if m in top else "")
        print(f"  {'OK  ' if ok else 'MISS'}  {m}" + (f"  ({where})" if where else ""))
    print(f"  （PYZ 共 {len(mods)} 个模块；CArchive 顶层 {len(keys)} 条）")

    # ---- 2) 数据文件：逐字节比对 ----
    print("\n[2] 数据文件（原样打包，可逐字节比对）")
    for want in WANT_DATA:
        hit = [k for k in keys if norm(k).endswith(want)]
        if not hit:
            print(f"  MISS  {want}")
            bad += 1
            continue
        src_path = os.path.join(ROOT, want.replace("/", os.sep))
        if not os.path.exists(src_path):
            print(f"  OK    {want}  （exe 内有；源码缺失，跳过比对）")
            continue
        src = open(src_path, "rb").read()
        got = r.extract(hit[0])
        same = hashlib.md5(src).hexdigest() == hashlib.md5(got).hexdigest()
        if not same:
            bad += 1
        print(f"  {'OK  ' if same else 'DIFF'}  {want}  {'字节一致' if same else '不一致!'}")

    print()
    if bad:
        print(f"结论：{bad} 项有问题。")
        return 1
    print("结论：通过 —— 本次改动涉及的模块与前端资源均已装入冻结产物。")
    print("      行为级证明请再跑一次装机版 API 测试（/api/health 报 0.4.0 + /api/egress/* 可用）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
