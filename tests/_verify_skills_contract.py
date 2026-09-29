# -*- coding: utf-8 -*-
"""Skills 体系 LibreChat 字段契约验收（目标任务书 2026-09-28 · 任务 2）。

验收口径：
  1. `/api/skills/list`（含 folder 技能）返回的每条技能 100% 含 LibreChat 字段契约
     —— 本测试在模块层验证 skills_catalog 的契约映射 + api 路由的统一收口逻辑；
  2. 损坏 / 缺失 frontmatter 的 SKILL.md 必须跳过且不崩（反向验证）；
  3. inject_text() 在有技能时非空（指令层注入不污染 system）。

退出码：0 = 全部通过；1 = 有失败。
"""
import os
import sys
import tempfile

# 让 `from core import skills_catalog` 可用（仓库根在 sys.path）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import skills_catalog  # noqa: E402

CONTRACT_STR = ("name", "description", "trigger", "risk", "version", "category")
CONTRACT_LIST = ("allowed_tools", "tags")


def check(name, ok, detail=""):
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))
    return 0 if ok else 1


def main():
    print("=" * 76)
    print("Skills 体系 · LibreChat 字段契约验收")
    print("=" * 76)
    fails = 0

    # ---- 1. folder 技能 100% 含契约字段 ----
    print("\n[1] folder 技能契约字段全覆盖（skills_catalog.scan_skills）")
    res = skills_catalog.scan_skills()
    sk = res["skills"]
    print(f"  扫描到 {len(sk)} 个技能 / 跳过 {len(res['skipped'])} 个")
    if not sk:
        print("  !! 没有任何 folder 技能，无法验证契约（环境异常）")
        return 1
    for f in CONTRACT_STR:
        bad = [s["name"] for s in sk if f not in s or not isinstance(s.get(f), str)]
        fails += check(f"标量字段 `{f}` 全覆盖（{len(sk) - len(bad)}/{len(sk)}）", len(bad) == 0,
                       ("缺: " + ",".join(bad[:5]) if bad else ""))
    for f in CONTRACT_LIST:
        bad = [s["name"] for s in sk if f not in s or not isinstance(s.get(f), list)]
        fails += check(f"列表字段 `{f}` 全覆盖（{len(sk) - len(bad)}/{len(sk)}）", len(bad) == 0,
                       ("缺: " + ",".join(bad[:5]) if bad else ""))

    # ---- 2. 路由统一收口：folder + T6 合成一条列表后 100% 契约 ----
    print("\n[2] 路由合并收口（folder + T6 模拟）normalize_contract")
    fake_t6 = {"id": "t6-abc", "type": "learned", "question": "如何算经济补偿",
               "skill_text": "按 N+1 计算", "created_at": "2026-09-28"}
    merged = [sk[0], fake_t6]  # 一个 folder 技能 + 一个 T6 技能
    norm = [skills_catalog.normalize_contract(it) for it in merged]
    for it in norm:
        for f in CONTRACT_STR + CONTRACT_LIST:
            if f not in it or (f in CONTRACT_LIST and not isinstance(it[f], list)) \
               or (f in CONTRACT_STR and not isinstance(it[f], str)):
                fails += check(f"合并列表字段 `{f}` 补齐", False, f"item={it.get('name')}")
                break
    else:
        fails += check("合并列表 100% 契约补齐", True)

    # ---- 3. 坏 frontmatter 跳过且不崩（反向验证）----
    print("\n[3] 坏 frontmatter 跳过且不崩（反向验证）")
    # 3a. 直接对 _parse_frontmatter 喂畸形输入，必须 None 且不抛
    malformed = [
        "根本没有 frontmatter 的正文",
        "---\n---\n只有空 frontmatter",
        "---\ndescription: 有描述但缺 name\n---\nbody",
        "---\nname: ok\n 坏掉的块标量: |\n  这行缩进\nname: 重复键\n---\nbody",
    ]
    parse_ok = True
    for m in malformed:
        try:
            r = skills_catalog._parse_frontmatter(m)
            if r is not None and not r["meta"].get("name"):
                parse_ok = False
        except Exception as e:  # noqa: BLE001
            parse_ok = False
            print(f"     !! 抛异常: {e}")
    fails += check("畸形 frontmatter 均被判定为损坏（返回 None，不抛栈）", parse_ok)

    # 3b. 真实落盘一个坏 SKILL.md，确认不被加载且可观测、清理后恢复
    broken_dir = os.path.join(skills_catalog.SKILLS_DIR, "_contract_test_broken")
    broken_md = os.path.join(broken_dir, "SKILL.md")
    os.makedirs(broken_dir, exist_ok=True)
    try:
        with open(broken_md, "w", encoding="utf-8") as fh:
            fh.write("---\ndescription: 故意缺 name 的损坏技能\n---\nbody\n")
        # 触发重新扫描（新建文件改变目录 mtime，清缓存）
        skills_catalog._skills_cache["val"] = None
        lst = skills_catalog.list_skills()
        names = {s["name"] for s in lst}
        skipped = skills_catalog.get_skipped()
        loaded_bad = any("contract_test_broken" in n for n in names)
        recorded = any("contract_test_broken" in s for s in skipped)
        fails += check("坏 SKILL.md 未进入技能列表（不崩）", not loaded_bad)
        fails += check("坏 SKILL.md 被记入 skipped（可观测）", recorded,
                       ("skipped=" + str(skipped) if not recorded else ""))
    finally:
        # 清理：删掉坏文件，恢复原状
        try:
            os.remove(broken_md)
            os.rmdir(broken_dir)
            skills_catalog._skills_cache["val"] = None
            skills_catalog.list_skills()  # 复位缓存
        except OSError:
            pass
    after = skills_catalog.get_skipped()
    fails += check("清理后 skipped 不再含坏文件", not any("contract_test_broken" in s for s in after))

    # ---- 4. inject_text 非空 ----
    print("\n[4] inject_text() 有技能时非空")
    txt = skills_catalog.inject_text()
    fails += check("inject_text 返回非空清单", bool(txt) and "可用技能清单" in txt)

    print()
    print("=" * 76)
    if fails:
        print(f"结论: 失败 —— {fails} 项")
        return 1
    print("结论: 通过 —— Skills 体系 100% 符合 LibreChat 字段契约，坏 frontmatter 跳过不崩。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
