"""把 mattpocock/skills 中精选的通用工程技能，装进 WorkBuddy 自身用户级技能库
（~/.workbuddy-ai/skills/<name>/），供助手后续会话直接调用。

- 只复制纯 Markdown 技能（含同目录 companion 文件），跳过 Claude-Code 专用 / 会生成 shell 的技能。
- 已存在同名技能则跳过（不覆盖）。
- 打印安装结果 + 卸载方法。
"""
import os
import glob
import shutil

SRC_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills", "mattpocock-skills", "skills")
DST_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy-ai", "skills")

# 精选：通用、纯指令、对助手日常工作有用
PICK = [
    "tdd", "diagnosing-bugs", "code-review", "codebase-design",
    "improve-codebase-architecture", "to-spec", "domain-modeling",
    "writing-for-agents", "grill-me", "research",
]


def find_skill_dir(name):
    hits = glob.glob(os.path.join(SRC_ROOT, "**", name, "SKILL.md"), recursive=True)
    return os.path.dirname(hits[0]) if hits else None


def main():
    os.makedirs(DST_ROOT, exist_ok=True)
    installed, skipped, missing = [], [], []
    for name in PICK:
        src = find_skill_dir(name)
        if not src:
            missing.append(name)
            continue
        dst = os.path.join(DST_ROOT, name)
        if os.path.exists(dst):
            skipped.append(name)
            continue
        shutil.copytree(src, dst)
        files = [f for f in os.listdir(dst)]
        installed.append((name, files))
    print("已安装到 %s：" % DST_ROOT)
    for name, files in installed:
        print("  + %-32s (%d 文件)" % (name, len(files)))
    if skipped:
        print("已存在跳过：", ", ".join(skipped))
    if missing:
        print("未找到：", ", ".join(missing))
    print("卸载：删除 %s 下对应目录即可（如 rm -r \"%s/tdd\"）" % (DST_ROOT, DST_ROOT))
    print("SELF_INSTALL_DONE")


if __name__ == "__main__":
    main()
