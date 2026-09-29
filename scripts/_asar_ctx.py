"""从 WorkBuddy app.asar 中提取关键词上下文，用于与 MiniYuxi 做一致性比对。

asar 内是超长压缩行，普通 grep 的 .{N} 上下文匹配会失败，故用字节窗口直接切片。
用法： python _asar_ctx.py 关键词1 关键词2 ...
"""
import sys

ASAR = r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar"


def contexts(data: bytes, kw: str, before: int = 120, after: int = 120, limit: int = 8):
    b = kw.encode("utf-8")
    out, i = [], 0
    while True:
        j = data.find(b, i)
        if j < 0:
            break
        s = data[max(0, j - before): j + len(b) + after].decode("utf-8", "replace")
        out.append(s.replace("\n", "\\n"))
        i = j + len(b)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    kws = sys.argv[1:] or ["新建对话", "Ctrl+N", "展开侧边栏", "收起侧边栏"]
    with open(ASAR, "rb") as fh:
        data = fh.read()
    print(f"asar size = {len(data):,} bytes")
    for kw in kws:
        hits = contexts(data, kw)
        print(f"\n{'=' * 18} {kw}  ({len(hits)} shown) {'=' * 18}")
        for s in hits:
            print("  |", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
