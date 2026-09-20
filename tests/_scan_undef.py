"""静态扫描 web/wb_workbench.js：找出「被调用但未定义」的函数名（前端回归硬卡点）。

这是「360 七坑 · 坑3 一键生成」的工程护栏：2026-09-16 曾因 saveMsgs/loadMsgs
等函数「只调用未定义」导致整页「无法对话」，靠真实浏览器才抓到。本脚本把该回归
固化为确定性检查，未过即阻断提交/合并。

判定（任一不满足即 exit 1）：
  1) 会话持久化关键函数必须全部定义：loadConvos/saveConvos/loadMsgs/saveMsgs/newConvo；
  2) 调用符号集合减去(已定义 ∪ 已知安全全局/别名)后必须为空，否则视为疑似未定义调用。

注：纯标准库，零依赖，可在 pre-commit / CI 中快速跑。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "web", "wb_workbench.js")
js = open(SRC, encoding="utf-8").read()

# 去注释与字符串，避免误判
clean = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
clean = re.sub(r"//[^\n]*", " ", clean)

defined = set()
defined |= set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", clean))
defined |= set(re.findall(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*function", clean))
defined |= set(re.findall(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", clean))
# 形参也算定义（回调形参易误报）
for group in re.findall(r"function\s*[\w$]*\s*\(([^)]*)\)", clean):
    for p in group.split(","):
        p = p.strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
            defined.add(p)

builtin = {
    "function", "if", "for", "while", "switch", "catch", "return", "typeof", "new",
    "Promise", "Array", "Object", "String", "Number", "Boolean", "JSON", "Math", "Date",
    "RegExp", "Error", "Map", "Set", "Symbol", "parseInt", "parseFloat", "isNaN",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval", "requestAnimationFrame",
    "cancelAnimationFrame", "fetch", "encodeURIComponent", "decodeURIComponent", "alert",
    "require", "await", "async", "delete", "void", "in", "of", "do", "else", "try",
    "console", "localStorage", "sessionStorage", "document", "window", "navigator",
    "performance", "matchMedia", "getComputedStyle", "addEventListener", "Blob",
    "FileReader", "URL", "Event", "CustomEvent", "FormData", "EventTarget", "Node",
    "HTMLElement", "MutationObserver", "IntersectionObserver", "ResizeObserver",
    "AbortController", "TextEncoder", "TextDecoder", "URLSearchParams", "WebSocket",
    "XMLHttpRequest", "Intl", "Proxy", "Reflect", "WeakMap", "WeakSet", "structuredClone",
    "queueMicrotask", "Notification", "indexedDB", "crypto", "BroadcastChannel",
    "Audio", "Image", "requestIdleCallback", "cancelIdleCallback", "raf", "var",
}

# 已知安全别名 / 全局（保活，避免把合法别名当未定义）
SAFE_GLOBALS = builtin | {
    "raf", "var", "Event", "FormData",
}

calls = set(re.findall(r"(?<![\.\w$])([A-Za-z_$][\w$]*)\s*\(", clean))
unknown = sorted(c for c in calls - defined - SAFE_GLOBALS)

print("定义符号数:", len(defined))
print("调用符号数:", len(calls))

print("\n=== 疑似未定义的调用（前缀式，非成员方法）===")
if not unknown:
    print("  (无)")
for u in unknown:
    lines = [i + 1 for i, l in enumerate(js.splitlines()) if re.search(r"(?<![\.\w$])" + re.escape(u) + r"\s*\(", l)]
    print(f"  {u:<24} 出现在行 {lines[:8]}{' ...' if len(lines) > 8 else ''}")

print("\n=== 会话持久化函数定义检查（坑3 回归关键项）===")
REQUIRED = ["loadConvos", "saveConvos", "loadMsgs", "saveMsgs", "newConvo"]
missing = []
for fn in REQUIRED:
    has_def = (f"function {fn}" in clean) or re.search(r"(?:var|let|const)\s+" + fn + r"\s*=", clean)
    n_call = len(re.findall(r"(?<![\.\w$])" + fn + r"\s*\(", clean))
    print(f"  {fn:<14} 定义: {'✅' if has_def else '❌ 缺失'}   调用 {n_call} 处")
    if not has_def:
        missing.append(fn)

# 判定
ok = True
if unknown:
    ok = False
    print("\n❌ 存在疑似未定义的函数调用，阻断提交（请补齐定义或加入 SAFE_GLOBALS 白名单）。")
if missing:
    ok = False
    print("\n❌ 会话持久化关键函数缺失：%s，阻断提交。" % ", ".join(missing))

sys.exit(0 if ok else 1)
