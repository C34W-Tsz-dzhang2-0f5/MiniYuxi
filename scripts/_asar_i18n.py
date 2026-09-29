"""从 WorkBuddy app.asar 中导出指定 i18n 命名空间的完整文案块。

WorkBuddy 前端文案以 JSON 形式内嵌，形如  sidebar: { "newChat": "新对话", ... }。
本脚本按 `键名: {` 定位，做花括号配平后原样输出，便于与 MiniYuxi 逐条比对。
用法： python _asar_i18n.py sidebar nav topbar settings
"""
import sys

ASAR = r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar"


def extract_block(text: str, key: str, limit: int = 4000) -> list[str]:
    """取出 `key: { ... }` 的配平块（最多 limit 字符）。"""
    out = []
    needle = f'{key}: {{'
    i = 0
    while True:
        j = text.find(needle, i)
        if j < 0:
            break
        depth, k = 0, j + len(key)
        while k < len(text) and k - j < limit:
            c = text[k]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(text[j:k + 1].replace("\n", "\\n").replace("\t", ""))
        i = j + len(key)
        if len(out) >= 3:
            break
    return out


def main() -> int:
    keys = sys.argv[1:] or ["sidebar"]
    with open(ASAR, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    for key in keys:
        blocks = extract_block(text, key)
        print(f"\n{'=' * 20} {key}  ({len(blocks)} block(s)) {'=' * 20}")
        for b in blocks:
            print(b[:2600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
