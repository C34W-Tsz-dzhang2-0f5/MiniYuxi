"""从 WorkBuddy asar 中提取「每个 tab 的完整 chip 列表（欢迎页 scenes）」的源配置。

之前的 _asar_scenes.py 只搜了 tab 名和个别 chip。
这里重点找：
  - "生成图片" / "生成视频" 所在的数组（设计创意）
  - 欢迎页 scenes 数据源（homepageScenes / WELCOME_SCENES / quickActionsByMode）
  - 每个 mode 对应的 scene 列表
"""
import json
from pathlib import Path

ASAR = Path(r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar")
OUT = Path(__file__).resolve().parents[1] / "docs" / "_wb_scene_groups.json"


def window(data: bytes, kw: bytes, before: int = 500, after: int = 1800, limit: int = 6):
    out, i = [], 0
    while True:
        j = data.find(kw, i)
        if j < 0:
            break
        s = data[max(0, j - before): j + len(kw) + after].decode("utf-8", "replace")
        out.append(s)
        i = j + len(kw)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    data = ASAR.read_bytes()
    print(f"asar size = {len(data):,} bytes")

    # 用字节搜索，避免 utf-8 解码失误
    probes = {
        # 设计创意 chips（带引号，找 JS 数组字面量）
        "quoted_生成图片": ("\"生成图片\"".encode(), 400, 1200),
        "quoted_生成视频": ("\"生成视频\"".encode(), 400, 1200),
        "quoted_个人工作台": ("\"个人工作台\"".encode(), 400, 1200),
        "quoted_深度研究": ("\"深度研究\"".encode(), 400, 1200),
        # 可能的欢迎页 scenes 配置
        "kw_welcomeScenes": ("welcomeScenes".encode(), 400, 1200),
        "kw_homepageScenes": ("homepageScenes".encode(), 400, 1200),
        "kw_quickActionsByMode": ("quickActionsByMode".encode(), 400, 1200),
        "kw_SCENES": ("SCENES =".encode(), 400, 1200),
        "kw_welcomeMode_design_scenes": ("welcomeMode === \"design\"".encode(), 400, 1400),
        "kw_designCapsules": ("designCapsules".encode(), 400, 1400),
        "kw_7_capsules": ("7 个胶囊".encode(), 600, 1800),
    }
    result = {}
    for name, (b, before, after) in probes.items():
        hits = window(data, b, before, after)
        result[name] = hits
        print(f"\n{'=' * 14} {name}  ({len(hits)} hits) {'=' * 14}")
        for s in hits:
            print("----")
            print(s.replace("\n", "\\n")[:1500])
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 已存 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())