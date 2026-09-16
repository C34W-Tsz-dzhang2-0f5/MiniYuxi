"""静态扫描 wb_workbench.js：找出「被调用但未定义」的函数名。

思路：正则收集 (a) 定义名（function X / var X = function / var X = (...) =>）
     (b) 调用名（X( ，排除关键字与已知内建）。
两者求差 -> 潜在 ReferenceError 隐患。
"""
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "web", "wb_workbench.js")
js = open(SRC, encoding="utf-8").read()

# 去注释与字符串，避免误判
clean = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
clean = re.sub(r"//[^\n]*", " ", clean)

defined = set()
defined |= set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", clean))
defined |= set(re.findall(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*function", clean))
defined |= set(re.findall(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", clean))
# 形参也算定义（回调形参易误报）
defined |= set(re.findall(r"function\s*[\w$]*\s*\(([^)]*)\)", clean))
params = set()
for group in re.findall(r"function\s*[\w$]*\s*\(([^)]*)\)", clean):
    for p in group.split(","):
        p = p.strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
            params.add(p)
defined |= params

builtin = {
    "function", "if", "for", "while", "switch", "catch", "return", "typeof", "new",
    "Promise", "Array", "Object", "String", "Number", "Boolean", "JSON", "Math", "Date",
    "RegExp", "Error", "Map", "Set", "Symbol", "parseInt", "parseFloat", "isNaN",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval", "requestAnimationFrame",
    "cancelAnimationFrame", "fetch", "encodeURIComponent", "decodeURIComponent", "alert",
    "require", "await", "async", "delete", "void", "in", "of", "do", "else", "try",
    "console", "localStorage", "document", "window", "navigator", "performance",
    "matchMedia", "getComputedStyle", "addEventListener", "Blob", "FileReader", "URL",
}

calls = set(re.findall(r"(?<![\.\w$])([A-Za-z_$][\w$]*)\s*\(", clean))
unknown = sorted(c for c in calls - defined - builtin)

print("定义符号数:", len(defined))
print("调用符号数:", len(calls))
print()
print("=== 疑似未定义的调用（前缀式，非成员方法）===")
if not unknown:
    print("  (无)")
for u in unknown:
    lines = [i + 1 for i, l in enumerate(js.splitlines()) if re.search(r"(?<![\.\w$])" + re.escape(u) + r"\s*\(", l)]
    print(f"  {u:<24} 出现在行 {lines[:8]}{' ...' if len(lines) > 8 else ''}")

print()
print("=== 会话持久化函数定义检查 ===")
for fn in ["loadConvos", "saveConvos", "loadMsgs", "saveMsgs", "convoKey", "newConvo", "selectConvo", "carryDraft"]:
    has_def = (f"function {fn}" in clean) or re.search(r"(?:var|let|const)\s+" + fn + r"\s*=", clean)
    n_call = len(re.findall(r"(?<![\.\w$])" + fn + r"\s*\(", clean))
    print(f"  {fn:<14} 定义: {'✅' if has_def else '❌ 缺失'}   调用 {n_call} 处")
