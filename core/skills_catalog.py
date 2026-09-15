# -*- coding: utf-8 -*-
"""指令层 Skill 注册表（橙皮书 Agent Skills 落地：自然语言"工作手册"=能力接口）。

职责：扫描项目根 skills/ 目录下所有 SKILL.md，解析 YAML frontmatter
(name/description/trigger)，对外提供 list_skills() / load_skill(name) / inject_text()。
设计约束（来自 /goal 任务书）：
- 纯标准库，无新增第三方依赖；
- 新建独立文件，不覆盖、不改动现有 core/skills.py（T6 对话经验沉淀）；
- frontmatter 损坏或缺失的 SKILL.md 必须跳过且不崩（反向验证要求）。

学 Hermes：技能清单通过 inject_text() 作为 user message 段注入，不污染 system 主结构。
"""
import glob
import os
import re

# skills/ 位于项目根（与 core/ 同级）
SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")


def _parse_frontmatter(text: str):
    """解析 YAML frontmatter（简单 key: value，被 --- 包裹）。

    返回 {"meta": {...}, "body": str}；无 frontmatter 或缺少 name 则返回 None（视为损坏/跳过）。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return None
    meta_raw, body = m.group(1), m.group(2)
    meta = {}
    for line in meta_raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    if not meta.get("name"):
        return None
    return {"meta": meta, "body": body}


def _scan() -> list:
    """扫描全部 SKILL.md，损坏/无 frontmatter 的跳过（不抛异常）。"""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for path in sorted(glob.glob(os.path.join(SKILLS_DIR, "**", "SKILL.md"), recursive=True)):
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        parsed = _parse_frontmatter(text)
        if parsed is None:
            continue
        out.append(
            {
                "name": parsed["meta"].get("name"),
                "description": parsed["meta"].get("description", ""),
                "trigger": parsed["meta"].get("trigger", ""),
                "toolset": parsed["meta"].get("toolset", "hr"),
                "path": path,
                "body": parsed["body"],
            }
        )
    return out


def list_skills() -> list:
    """列出全部已注册技能（dict 列表）。无任何技能时返回 []，不报错。"""
    return _scan()


def load_skill(name: str):
    """按 name 取单个技能完整信息；不存在返回 None。"""
    for s in _scan():
        if s["name"] == name:
            return s
    return None


def inject_text(limit: int = 8) -> str:
    """生成可注入的技能清单文本（作为 user message 段，不污染 system 主结构）。

    学 Hermes：技能清单作 user message 注入，保持 system prompt 主结构干净。
    """
    skills = list_skills()
    if not skills:
        return ""
    lines = ["【可用技能清单 · 命中 trigger 时按对应工作流执行】"]
    for s in skills[:limit]:
        trig = f"（触发：{s['trigger']}）" if s.get("trigger") else ""
        lines.append(f"- {s['name']}：{s['description']}{trig}")
    return "\n".join(lines)
