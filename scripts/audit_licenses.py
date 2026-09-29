#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""商用授权与数据外联审计（MiniYuxi「可商用」定位的尽调工具）

用途
----
MiniYuxi 定位为企业级、**可商用**。每次引入新依赖（npm 包 / 模型权重 / SDK）前，
用本脚本核两件事：

1. **授权是否干净** —— 扫描 node_modules（含传递依赖），列出授权分布，
   标出 copyleft（GPL/AGPL/LGPL/SSPL）等**不可商用或高风险**的包。
2. **是否偷偷外联** —— 扫描打包产物，列出全部 URL 主机，
   并对 telemetry/analytics/埋点类地址做告警（企业级不能有未告知的数据外发）。

用法
----
    # 审计某个前端 bundle 工程（自动找 node_modules）
    python scripts/audit_licenses.py --pkg tools/office-bundle

    # 同时审计打包产物
    python scripts/audit_licenses.py --pkg tools/office-bundle \\
        --bundle web/vendor/univer/univer.bundle.js

    # 只看结论（CI 友好：有问题时 exit 1）
    python scripts/audit_licenses.py --pkg tools/office-bundle --quiet

退出码
------
    0 = 全部宽松授权、无外联告警
    1 = 发现 copyleft / 未知授权 / 外联告警
    2 = 参数或路径错误
"""

import argparse
import collections
import json
import os
import re
import sys

# 可商用的宽松授权白名单（首段匹配，支持 "MIT OR Apache-2.0" 这类表达式）
PERMISSIVE = {
    "MIT", "MIT-0", "Apache-2.0", "Apache-2.0 WITH LLVM-exception",
    "ISC", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "BSD-4-Clause",
    "CC0-1.0", "Unlicense", "BlueOak-1.0.0", "Python-2.0", "Zlib", "WTFPL",
    "CC-BY-4.0", "CC-BY-3.0", "Public Domain",
}

# 明确不可商用 / 高风险的 copyleft（企业级闭源分发场景）
COPYLEFT = {
    "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-only",
    "GPL-3.0-or-later", "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later",
    "LGPL-2.1", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0",
    "LGPL-3.0-only", "LGPL-3.0-or-later", "SSPL-1.0", "BUSL-1.1",
    "Elastic-2.0", "Commons-Clause", "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0",
    "OSL-3.0", "EUPL-1.1", "EUPL-1.2", "CPAL-1.0",
}

# 疑似上报 / 埋点的地址特征
SUSPECT_URL = re.compile(
    r"(telemetry|analytics|report|track|beacon|collect|sentry|amplitude"
    r"|mixpanel|segment|umami|matomo|plausible|datadog|newrelic|bugsnag"
    r"|googletag|google-analytics|/log\.|/collect\b)",
    re.I,
)

URL_RE = re.compile(r"https?://[a-zA-Z0-9._~:/?#\[\]@!$&%()*+,;=/-]{4,200}")


def _first_clause(lic):
    """从 SPDX 表达式取用于判定的主授权（OR 取第一个，AND 取第一个）。"""
    return lic.split(" OR ")[0].split(" AND ")[0].strip()


def scan_packages(pkg_root):
    """扫描 node_modules，返回 (总数, 授权计数, 问题列表)。"""
    nm = os.path.join(pkg_root, "node_modules")
    if not os.path.isdir(nm):
        print("!! 找不到 %s —— 先在该工程执行 npm install" % nm, file=sys.stderr)
        return None, None, None

    counts = collections.Counter()
    copyleft_hits, unknown_hits = [], []
    total = 0

    for dirpath, dirnames, filenames in os.walk(nm):
        if "package.json" not in filenames:
            continue
        p = os.path.join(dirpath, "package.json")
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if "name" not in d or "version" not in d:
            continue
        # 跳过 rxjs/ajax 这类"子路径解析用"的伪包（无 version 已被上面过滤，这里再兜一层）
        if "/" in d["name"] and d["name"].split("/")[-1] in (
            "ajax", "fetch", "operators", "testing", "webSocket"
        ):
            continue

        total += 1
        lic = d.get("license") or d.get("licenses") or ""
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        if isinstance(lic, list):
            lic = " OR ".join(
                (x.get("type", "") if isinstance(x, dict) else str(x)) for x in lic
            )
        lic = (lic or "").strip() or "UNKNOWN"
        counts[lic] += 1

        base = _first_clause(lic)
        if base in COPYLEFT:
            copyleft_hits.append((d["name"], lic, d.get("version", "")))
        elif base not in PERMISSIVE:
            unknown_hits.append((d["name"], lic, d.get("version", "")))

    return total, counts, (copyleft_hits, unknown_hits)


def scan_bundle(path):
    """扫描打包产物里的 URL，返回 (字节数, 主机计数, 疑似上报列表)。"""
    if not os.path.isfile(path):
        print("!! 找不到产物 %s" % path, file=sys.stderr)
        return None, None, None
    size = os.path.getsize(path)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        src = fh.read()

    urls = URL_RE.findall(src)
    hosts = collections.Counter()
    for u in urls:
        m = re.match(r"https?://([^/:]+)", u)
        if m:
            hosts[m.group(1)] += 1
    suspects = sorted({u for u in urls if SUSPECT_URL.search(u)})
    return size, (len(urls), hosts), suspects


def main():
    ap = argparse.ArgumentParser(
        description="MiniYuxi 商用授权与数据外联审计",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pkg", required=True,
                    help="含 node_modules 的工程目录（如 tools/office-bundle）")
    ap.add_argument("--bundle", default="",
                    help="可选：打包产物路径，做外联审计")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args()

    if not os.path.isdir(args.pkg):
        print("!! --pkg 不是目录: %s" % args.pkg, file=sys.stderr)
        return 2

    problems = []

    # ---------- 1. 授权 ----------
    total, counts, hits = scan_packages(args.pkg)
    if total is None:
        return 2
    copyleft_hits, unknown_hits = hits

    if not args.quiet:
        print("=" * 66)
        print("① 授权审计  ——  %s" % os.path.join(args.pkg, "node_modules"))
        print("=" * 66)
        print("扫描包数（含传递依赖）: %d" % total)
        print()
        print("%-4s %-30s %s" % ("", "授权", "数量"))
        print("-" * 66)
        for lic, n in counts.most_common():
            base = _first_clause(lic)
            mark = "OK " if base in PERMISSIVE else (
                "XX " if base in COPYLEFT else "?? ")
            print("%-4s %-30s %d" % (mark, lic, n))
        print()

    if copyleft_hits:
        problems.append("copyleft 授权 %d 个" % len(copyleft_hits))
        print("!! 不可商用 / 高风险（copyleft）:")
        for n, l, v in sorted(set(copyleft_hits)):
            print("   XX %-42s %-22s %s" % (n, l, v))
    if unknown_hits:
        problems.append("未知授权 %d 个" % len(unknown_hits))
        print("!! 授权未识别，需人工确认:")
        for n, l, v in sorted(set(unknown_hits)):
            print("   ?? %-42s %-22s %s" % (n, l, v))
    if not copyleft_hits and not unknown_hits:
        print("OK 全部为宽松授权，可商用无阻。")

    # ---------- 2. 外联 ----------
    if args.bundle:
        size, info, suspects = scan_bundle(args.bundle)
        if size is None:
            return 2
        nurls, hosts = info
        if not args.quiet:
            print()
            print("=" * 66)
            print("② 数据外联审计  ——  %s" % args.bundle)
            print("=" * 66)
            print("产物大小: %.1f MB   URL 总数: %d" % (size / 1024 / 1024, nurls))
            print()
            print("--- 出现的主机（按次数）---")
            for h, c in hosts.most_common():
                print("   %-48s %d" % (h, c))
            print()
        if suspects:
            problems.append("疑似上报/埋点地址 %d 个" % len(suspects))
            print("!! 疑似上报 / 埋点地址:")
            for u in suspects:
                print("   XX %s" % u)
        else:
            print("OK 未发现 telemetry / analytics / 埋点地址。")
        print()
        print("提示: 高频域名若是常量字符串（如公式错误码的文档链接、"
              "XML 命名空间）属正常，非运行时外呼。")

    # ---------- 结论 ----------
    print()
    print("=" * 66)
    if problems:
        print("结论: 需处理 —— " + "；".join(problems))
        return 1
    print("结论: 通过 —— 授权干净、无未告知外联。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
