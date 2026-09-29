"""从 WorkBuddy app.asar 中枚举快捷键注册表（defaultWin/defaultMac），用于与 MiniYuxi 比对。

WorkBuddy 的快捷键以 { id, category, scope, defaultMac, defaultWin, editable } 结构声明，
本脚本按 defaultWin 定位并向前回溯 id / labelKey / category。
"""
import re

ASAR = r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar"

ENTRY = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)"\s*,\s*'
    r'(?:labelKey:\s*"(?P<label>[^"]+)"\s*,\s*)?'
    r'(?:category:\s*"(?P<cat>[^"]+)"\s*,\s*)?'
    r'(?:scope:\s*"(?P<scope>[^"]+)"\s*,\s*)?'
    r'defaultMac:\s*"(?P<mac>[^"]*)"\s*,\s*'
    r'defaultWin:\s*"(?P<win>[^"]*)"',
    re.S,
)


def main() -> int:
    with open(ASAR, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    seen, rows = set(), []
    for m in ENTRY.finditer(text):
        win = m.group("win")
        sid = m.group("id")
        key = (sid, win)
        if key in seen:
            continue
        seen.add(key)
        rows.append((sid, m.group("cat") or "", win, m.group("mac") or "", m.group("label") or ""))
    print(f"共解析出 {len(rows)} 条快捷键\n")
    print(f"{'id':<58} {'category':<12} {'Win':<16} {'Mac':<14} labelKey")
    print("-" * 130)
    for sid, cat, win, mac, label in rows:
        print(f"{sid:<58} {cat:<12} {win:<16} {mac:<14} {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
