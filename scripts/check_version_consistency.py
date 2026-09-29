#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""版本号一致性校验（防再次漂移）。

背景
----
2026-09-24 排查发现版本号有多个独立副本且互相漂移：
    api.py             -> "0.1.0"    （FastAPI app version + /api/health 对外返回）
    core/mcp_client.py -> "0.1.0"    （MCP clientInfo）
    run.py / cli.py / pyproject.toml / tauri.conf.json / package.json / Cargo.toml -> "0.2.0"
    CHANGELOG.md       -> 最新已发布 0.2.2
对「企业级、可商用」的交付来说，对外报三个不同版本号是硬伤。

本脚本做两件事
--------------
1. **跨清单比对**：`core/version.py` 的 `__version__` 必须与
   `pyproject.toml` / `tauri.conf.json` / `apps/desktop/package.json` /
   `apps/desktop/src-tauri/Cargo.toml` / `CHANGELOG.md` 顶部已发布版本 全部一致。
2. **扫「野生」版本字面量**：源码里除 `core/version.py` 外，不允许再出现
   `VERSION = "x.y.z"` 这类硬编码（正是漂移的源头）。

用法
----
    python scripts/check_version_consistency.py
    python scripts/check_version_consistency.py --quiet     # 只输出结论（CI 友好）

退出码
------
    0 = 一致
    1 = 发现不一致或野生版本字面量
    2 = 文件缺失 / 解析失败
"""

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOT_FILE = os.path.join("core", "version.py")
CHANGELOG = "CHANGELOG.md"

# 需要与 SOT 保持一致的「手写清单」（无法 import Python，只能靠本脚本强制）
MANIFESTS = [
    ("pyproject.toml", "toml", "project", "version"),
    ("apps/desktop/src-tauri/tauri.conf.json", "json", None, "version"),
    ("apps/desktop/package.json", "json", None, "version"),
    ("apps/desktop/src-tauri/Cargo.toml", "toml", "package", "version"),
]

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

# 野生版本字面量：形如  VERSION = "1.2.3" / SIDECAR_VERSION = "1.2.3" /
#                        __version__ = "1.2.3" / "version": "1.2.3"
#
# ⚠️ 这个 key 模式是 2026-09-24 反复用负例试出来的，三个易错点：
#    1. 不能用 `\bVERSION\b` —— `_` 是词字符，`API_VERSION` 里 `VERSION` 前没有词边界，
#       会**漏掉**这种最常见的回归形态。要显式写 `[A-Za-z]+_VERSION`。
#    2. 必须加 `re.IGNORECASE` —— 否则只处理首字母大小写，全大写 `VERSION` 匹配不上。
#    3. 不能用 `[A-Za-z_]*version[A-Za-z_]*` —— 那样会把 `conversion` 之类普通单词误伤。
#       显式列三种合法形态：裸 version / __version__ / XXX_VERSION。
WILD_RE = re.compile(
    r"""(?P<key>"""
    r"""\b__version__\b"""          # __version__
    r"""|\bversion\b"""             # version = / VERSION =
    r"""|\b[A-Za-z]+_version\b"""   # SIDECAR_VERSION / API_VERSION ...
    r"""|["']version["']"""         # {"version": ...}
    r""")"""
    r"""\s*[=:]\s*["'](?P<ver>\d+\.\d+\.\d+)["']""",
    re.IGNORECASE,
)

# 例外：这些是**别的命名空间**的版本号，不是产品版本，不该强行统一。
#   serverInfo —— MCP 服务端在 initialize 握手时自报的版本（如内置只读 fs 服务），
#                 它描述的是那个 MCP 服务自身，与 MiniYuxi 产品版本无关。
WILD_EXEMPT_MARKERS = ("serverInfo",)

SCAN_EXT = (".py",)
SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", "target",
             "dist", "build", "_work", "data"}


def read_sot():
    """从 core/version.py 取 __version__（唯一来源）。"""
    p = os.path.join(ROOT, SOT_FILE)
    if not os.path.isfile(p):
        print("!! 找不到 %s" % SOT_FILE, file=sys.stderr)
        return None
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"""^__version__\s*=\s*["']([^"']+)["']""", line.strip())
            if m:
                return m.group(1)
    print("!! %s 里没有 __version__ 赋值" % SOT_FILE, file=sys.stderr)
    return None


def _toml_load(path):
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        pass
    except Exception as e:
        print("!! TOML 解析失败 %s: %s" % (path, e), file=sys.stderr)
        return None
    # 兜底：极简正则（只取 section 下的 version）
    try:
        with open(path, encoding="utf-8") as fh:
            txt = fh.read()
        return {"__raw__": txt}
    except Exception as e:
        print("!! 读取失败 %s: %s" % (path, e), file=sys.stderr)
        return None


def read_manifest(rel, kind, section, key):
    """读一个清单里的版本号。"""
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None, "文件不存在"
    if kind == "json":
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh).get(key), None
        except Exception as e:
            return None, "JSON 解析失败: %s" % e
    # toml
    data = _toml_load(p)
    if data is None:
        return None, "TOML 解析失败"
    if "__raw__" in data:  # 无 tomllib 的兜底路径
        m = re.search(r"^\[\s*%s\s*\][\s\S]*?^version\s*=\s*[\"']([^\"']+)[\"']"
                      % re.escape(section or ""), data["__raw__"], re.M)
        return (m.group(1) if m else None), (None if m else "未找到 version")
    sec = data.get(section or "", {})
    return sec.get(key), (None if sec.get(key) else "未找到 version")


def read_changelog_version():
    """取 CHANGELOG 顶部第一个**已发布**版本（跳过 Unreleased）。"""
    p = os.path.join(ROOT, CHANGELOG)
    if not os.path.isfile(p):
        return None, "文件不存在"
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^##\s+\[([^\]]+)\]", line.strip())
            if not m:
                continue
            v = m.group(1)
            if v.lower() == "unreleased":
                continue
            return v, None
    return None, "未找到已发布版本标题"


def scan_wild_literals():
    """扫源码里除 core/version.py 外的硬编码版本字面量。"""
    hits = []
    sot_abs = os.path.abspath(os.path.join(ROOT, SOT_FILE))
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(SCAN_EXT):
                continue
            fp = os.path.join(dirpath, fn)
            if os.path.abspath(fp) == sot_abs:
                continue
            try:
                with open(fp, encoding="utf-8") as fh:
                    for i, line in enumerate(fh, 1):
                        s = line.strip()
                        if s.startswith("#"):
                            continue
                        if any(mk in line for mk in WILD_EXEMPT_MARKERS):
                            continue
                        for m in WILD_RE.finditer(line):
                            hits.append((os.path.relpath(fp, ROOT), i,
                                         m.group("key"), m.group("ver")))
            except Exception:
                continue
    return hits


def main():
    ap = argparse.ArgumentParser(description="MiniYuxi 版本号一致性校验")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args()

    sot = read_sot()
    if not sot:
        return 2
    if not SEMVER_RE.match(sot):
        print("!! core/version.py 的 __version__ 不是合法 SemVer: %r" % sot, file=sys.stderr)
        return 2

    problems = []
    rows = []

    for rel, kind, section, key in MANIFESTS:
        val, err = read_manifest(rel, kind, section, key)
        rows.append((rel, val, err))
    cl_val, cl_err = read_changelog_version()
    rows.append((CHANGELOG + "（顶部已发布）", cl_val, cl_err))

    if not args.quiet:
        print("=" * 74)
        print("版本号一致性校验")
        print("=" * 74)
        print("唯一来源 %s: %s" % (SOT_FILE, sot))
        print()
        print("%-46s %-12s %s" % ("位置", "版本", "状态"))
        print("-" * 74)

    for rel, val, err in rows:
        if err:
            problems.append("%s: %s" % (rel, err))
            status = "!! " + err
        elif val == sot:
            status = "OK"
        else:
            problems.append("%s = %s（应为 %s）" % (rel, val, sot))
            status = "XX 不一致"
        if not args.quiet:
            print("%-46s %-12s %s" % (rel, val or "-", status))

    wild = scan_wild_literals()
    if wild:
        for fp, ln, key, ver in wild:
            problems.append("野生版本字面量 %s:%d  %s = %r" % (fp, ln, key, ver))
        if not args.quiet:
            print()
            print("!! 野生版本字面量（应改为 import core.version）:")
            for fp, ln, key, ver in wild:
                print("   XX %s:%d  %s = %r" % (fp, ln, key, ver))
    elif not args.quiet:
        print()
        print("OK 源码中无野生版本字面量（除 %s）" % SOT_FILE)

    print()
    print("=" * 74)
    if problems:
        print("结论: 不一致 —— %d 项" % len(problems))
        if args.quiet:
            for p in problems:
                print("   XX %s" % p)
        return 1
    print("结论: 通过 —— 全部 %d 处版本号一致（%s）" % (len(rows) + 1, sot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
