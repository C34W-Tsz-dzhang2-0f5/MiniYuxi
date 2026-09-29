"""从 WorkBuddy 桌面端 app.asar 中提取「一致性对齐」所需的 UI 基准，产出 docs/_wb_baseline.json。

背景：WorkBuddy 桌面端是闭源 Electron 应用，无法用 Playwright/CDP 挂载遍历界面。
但其前端文案与配置以明文 JSON/JS 内嵌在 app.asar（无加密、未压缩成字节码），
因此可用「字节切片 + 花括号配平」的方式把以下四类基准原样抠出来：

  1. nav        —— 顶部导航注册表（id / target / order / children）
  2. sidebar    —— 会话侧边栏 i18n 文案全表
  3. shortcuts  —— 快捷键注册表（defaultWin / defaultMac / editable）
  4. scenes     —— 场景标签命中计数（用于核对 MiniYuxi 场景分组来源）

用法： python scripts/extract_wb_baseline.py
产出： docs/_wb_baseline.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ASAR = Path(r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddyAI\resources\app.asar")
REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "_wb_baseline.json"

# 快捷键条目：{ id, [labelKey], [category], [scope], defaultMac, defaultWin }
SHORTCUT_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)"\s*,\s*'
    r'(?:labelKey:\s*"(?P<label>[^"]+)"\s*,\s*)?'
    r'(?:category:\s*"(?P<cat>[^"]+)"\s*,\s*)?'
    r'(?:scope:\s*"(?P<scope>[^"]+)"\s*,\s*)?'
    r'defaultMac:\s*"(?P<mac>[^"]*)"\s*,\s*'
    r'defaultWin:\s*"(?P<win>[^"]*)"',
    re.S,
)

SCENE_PROBES = ["幻灯片", "视频生成", "深度研究", "文档处理", "数据分析", "可视化",
                "金融服务", "产品管理", "设计", "邮件编辑", "代码补全", "重构建议",
                "单元测试", "代码审查", "Bug 定位", "接口联调", "性能分析", "SQL 优化"]


def balanced_block(text: str, key: str, limit: int = 6000) -> list[str]:
    """取出 `key: { ... }` 的花括号配平块。"""
    out, needle, i = [], f"{key}: {{", 0
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
        out.append(text[j:k + 1])
        i = j + len(key)
        if len(out) >= 3:
            break
    return out


def main() -> int:
    if not ASAR.exists():
        raise SystemExit(f"✗ 找不到 WorkBuddy asar：{ASAR}")
    raw = ASAR.read_bytes()
    text = raw.decode("utf-8", "replace")

    # --- 1. 导航注册表 ---
    nav_blocks = balanced_block(text, "nav")
    nav_block = next((b for b in nav_blocks if "builtin:" in b), "")

    # --- 2. 侧边栏 i18n（取第一个含 newChat 的块，通常是英文基准）---
    side_blocks = balanced_block(text, "sidebar")
    side_en = next((b for b in side_blocks if '"newChat": "New Chat"' in b), side_blocks[0] if side_blocks else "")

    # --- 3. 快捷键 ---
    seen, shortcuts = set(), []
    for m in SHORTCUT_RE.finditer(text):
        key = (m.group("id"), m.group("win"))
        if key in seen:
            continue
        seen.add(key)
        shortcuts.append({
            "id": m.group("id"),
            "labelKey": m.group("label") or "",
            "category": m.group("cat") or "",
            "scope": m.group("scope") or "",
            "win": m.group("win"),
            "mac": m.group("mac"),
        })
    shortcuts.sort(key=lambda r: (r["category"], r["id"]))

    # --- 4. 场景标签命中计数 ---
    scenes = {s: raw.count(s.encode("utf-8")) for s in SCENE_PROBES}

    # --- 5. 会话恢复机制证据（原文片段）---
    restore_hits = []
    for kw in ["isRestoringSession", "restoreSessionTabs"]:
        b = kw.encode("utf-8")
        pos = raw.find(b)
        if pos >= 0:
            restore_hits.append(raw[max(0, pos - 260): pos + 260].decode("utf-8", "replace"))

    data = {
        "source": str(ASAR),
        "asar_bytes": len(raw),
        "nav_registry_raw": nav_block,
        "sidebar_i18n_raw": side_en,
        "shortcuts": shortcuts,
        "shortcut_count": len(shortcuts),
        "scene_label_hits": scenes,
        "session_restore_evidence": restore_hits,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 已写出 {OUT}")
    print(f"  asar 大小   : {len(raw):,} bytes")
    print(f"  导航条目    : {'已提取' if nav_block else '未提取到'}")
    print(f"  侧边栏文案  : {'已提取' if side_en else '未提取到'}")
    print(f"  快捷键      : {len(shortcuts)} 条")
    print(f"  场景标签    : {sum(1 for v in scenes.values() if v)}/{len(SCENE_PROBES)} 命中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
