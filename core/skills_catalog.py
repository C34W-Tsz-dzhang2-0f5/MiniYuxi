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


def _strip_quotes(v: str) -> str:
    """剥离 YAML 标量外侧成对引号（name: "xxx" → xxx），避免脏引号污染下游。"""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    return v


def _parse_frontmatter(text: str):
    """解析 YAML frontmatter（被 --- 包裹）。

    支持：key: value（自动剥引号）、块标量 key: | / >（收集缩进行）。
    返回 {"meta": {...}, "body": str}；无 frontmatter 或缺少 name 则返回 None（视为损坏/跳过）。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return None
    meta_raw, body = m.group(1), m.group(2)
    meta = {}
    lines = meta_raw.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#") or ":" not in s:
            i += 1
            continue
        k, v = s.split(":", 1)
        k = k.strip().lower()
        v = v.strip()
        if v in ("|", ">", "|-", ">-", "|+", ">+"):
            # 块标量：收集后续缩进/空行，直到出现顶格 key
            block = []
            i += 1
            while i < len(lines) and (lines[i][:1] in (" ", "\t") or not lines[i].strip()):
                if lines[i].strip():
                    block.append(lines[i].strip())
                i += 1
            meta[k] = "\n".join(block).strip()
            continue
        meta[k] = _strip_quotes(v)
        i += 1
    if not meta.get("name"):
        meta["name"] = ""
    if not meta["name"]:
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


# 目录级缓存：skills/ 目录 mtime 不变则直接返回上次扫描结果，
# 避免每次 /api/skills/list（UI 高频调用）都做递归 glob 扫描文件系统。
_skills_cache = {"mtime": 0.0, "val": None}


def list_skills() -> list:
    """列出全部已注册技能（dict 列表）。无任何技能时返回 []，不报错。

    按 skills/ 目录 mtime 做缓存：目录未变动时跳过 glob 递归扫描。
    """
    try:
        mtime = os.path.getmtime(SKILLS_DIR) if os.path.isdir(SKILLS_DIR) else 0.0
    except OSError:
        mtime = 0.0
    if _skills_cache["val"] is not None and _skills_cache["mtime"] == mtime:
        return _skills_cache["val"]
    val = _scan()
    _skills_cache["mtime"] = mtime
    _skills_cache["val"] = val
    return val


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
