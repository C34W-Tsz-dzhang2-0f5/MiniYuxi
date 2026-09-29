"""从 WorkBuddy app.asar 中提取「场景 tab 分组 + 每组 chips」的真实定义。

思路：asar 内是超长压缩行，grep 上下文会失败。这里用字节窗口切片 + 宽窗口，
围绕三个分组名（日常办公 / 代码开发 / 设计创意）和若干标志性 chip 抓取上下文。

用法： python scripts/_asar_scenes.py
"""
import json
from pathlib import Path

ASAR = Path(r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar")
OUT = Path(__file__).resolve().parents[1] / "docs" / "_wb_scenes_raw.json"


def window(data: bytes, kw: str, before: int = 600, after: int = 1400, limit: int = 4):
    b = kw.encode("utf-8")
    out, i = [], 0
    while True:
        j = data.find(b, i)
        if j < 0:
            break
        s = data[max(0, j - before): j + len(b) + after].decode("utf-8", "replace")
        out.append(s)
        i = j + len(b)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    if not ASAR.exists():
        raise SystemExit(f"✗ 找不到 asar：{ASAR}")
    data = ASAR.read_bytes()
    print(f"asar size = {len(data):,} bytes")

    probes = {
        "tab_日常办公": ("日常办公", 300, 1600),
        "tab_代码开发": ("代码开发", 300, 1600),
        "tab_设计创意": ("设计创意", 300, 1600),
        "chip_视觉海报": ("视觉海报", 400, 400),
        "chip_运营海报": ("运营海报", 400, 400),
        "chip_数据分析及可视化": ("数据分析及可视化", 400, 400),
        "chip_Agent应用": ("Agent 应用", 400, 400),
    }
    result = {}
    for name, (kw, before, after) in probes.items():
        hits = window(data, kw, before, after)
        result[name] = hits
        print(f"\n{'=' * 16} {name}  ({len(hits)} hits) {'=' * 16}")
        for s in hits:
            print("----")
            print(s.replace("\n", "\\n"))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 原始片段已存 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
