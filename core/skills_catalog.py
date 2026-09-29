# -*- coding: utf-8 -*-
"""指令层 Skill 注册表（对齐 LibreChat SKILL.md 契约）。

职责：扫描项目根 skills/ 目录下所有 SKILL.md，解析 YAML frontmatter，对外提供
list_skills() / load_skill(name) / inject_text() / scan_skills() / normalize_contract()。

字段契约（对齐 LibreChat，并补 MiniYuxi 扩展）：
- name          技能唯一 id（必填；缺失视为损坏、跳过）
- description   一句话能力说明（必填，用于注入与列表展示）
- trigger       自动触发词/场景（可选）
- risk          风险等级 low|medium|high（默认 low；高风险的技能后续接 HITL）
- allowed_tools 本技能允许调用的工具白名单（默认 []；后续接 toolset 约束）
- version       语义化版本（默认 "1.0.0"；对齐 Octop 的发布元数据）
- category      分类（默认取 toolset，否则 "general"）
- tags          标签列表（默认 []）
- toolset       历史字段，保留向后兼容（category 的别名来源）
- slug/display_name  兼容 WorkBuddy 风格元数据（透传，不进契约强制项）

设计约束（来自 /goal 任务书 + 目标任务书 2026-09-28）：
- 纯标准库，无新增第三方依赖；
- 新建独立文件，不覆盖、不改动现有 core/skills.py（T6 对话经验沉淀）；
- frontmatter 损坏或缺失的 SKILL.md 必须跳过且不崩（反向验证要求）；
- 注入走 inject_text() 作为 user message 段，不污染 system 主结构。
"""
import glob
import os
import re

# skills/ 位于项目根（与 core/ 同级）。
# ⚠️ 冻结（PyInstaller onefile）时 __file__ 落在临时解压目录 _MEIPASS，进程退出即删除 →
#    装进去的技能会「重启就丢」。因此允许 MINIYUXI_SKILLS_DIR 覆盖到持久目录；
#    run.py 的 _frozen_bootstrap() 会在 import core 之前把它指到 <MiniYuxi>/skills
#    并从内置技能播种一次。
_DEFAULT_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
SKILLS_DIR = os.getenv("MINIYUXI_SKILLS_DIR") or _DEFAULT_SKILLS_DIR


def _strip_quotes(v: str) -> str:
    """剥离 YAML 标量外侧成对引号（name: "xxx" → xxx），避免脏引号污染下游。"""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    return v


def _parse_list(v: str):
    """把 YAML 列表/逗号串解析为 Python list。
    支持 `[Read, Grep, Edit]` 与 `Read, Grep, Edit` 两种写法；空串返回 []。
    """
    if v is None:
        return []
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [x.strip().strip('"\'') for x in inner.split(",") if x.strip()] if inner else []
    if not v:
        return []
    return [x.strip().strip('"\'') for x in v.split(",") if x.strip()]


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


def _to_contract(meta: dict, path: str, body: str) -> dict:
    """把解析出的 meta 归一到 LibreChat 字段契约 + MiniYuxi 扩展。"""
    name = _strip_quotes(meta.get("name", ""))
    return {
        "name": name,
        "description": _strip_quotes(meta.get("description", "")),
        "trigger": _strip_quotes(meta.get("trigger", "")),
        "toolset": _strip_quotes(meta.get("toolset", "")),
        "risk": _strip_quotes(meta.get("risk", "low")) or "low",
        "allowed_tools": _parse_list(meta.get("allowed-tools") or meta.get("allowed_tools") or ""),
        "version": _strip_quotes(meta.get("version", "1.0.0")) or "1.0.0",
        "category": _strip_quotes(meta.get("category") or meta.get("toolset") or "general") or "general",
        "tags": _parse_list(meta.get("tags") or ""),
        "slug": _strip_quotes(meta.get("slug", "")),
        "display_name": _strip_quotes(meta.get("displayname") or meta.get("display_name") or ""),
        "path": path,
        "body": body,
    }


def _scan_with_skips() -> tuple:
    """扫描全部 SKILL.md；返回 (技能列表, 被跳过文件相对路径列表)。"""
    out = []
    skipped = []
    if not os.path.isdir(SKILLS_DIR):
        return out, skipped
    for path in sorted(glob.glob(os.path.join(SKILLS_DIR, "**", "SKILL.md"), recursive=True)):
        rel = os.path.relpath(path, SKILLS_DIR)
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            skipped.append(rel)
            continue
        parsed = _parse_frontmatter(text)
        if parsed is None:
            skipped.append(rel)
            continue
        out.append(_to_contract(parsed["meta"], path, parsed["body"]))
    return out, skipped


# 目录级缓存：skills/ 目录 mtime 不变则直接返回上次扫描结果，
# 避免每次 /api/skills/list（UI 高频调用）都做递归 glob 扫描文件系统。
_skills_cache = {"mtime": 0.0, "val": None}
_last_skipped = []


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
    skills, skipped = _scan_with_skips()
    _skills_cache["mtime"] = mtime
    _skills_cache["val"] = skills
    global _last_skipped
    _last_skipped = skipped
    return skills


def invalidate_cache() -> None:
    """清空扫描缓存。安装 / 卸载技能后必须调用：

    嵌套技能集合仓库的增删只改动**子目录** mtime，不改 SKILLS_DIR 顶层 mtime，
    因此仅靠 mtime 缓存会返回过期列表（删了还在、装了不显示）。
    """
    _skills_cache["mtime"] = -1.0
    _skills_cache["val"] = None


def scan_skills() -> dict:
    """无缓存全量扫描：返回 {"skills": [...], "skipped": [...], "total": N}。

    用于可观测：确认损坏 frontmatter 被正确跳过（skipped 计数 + 文件名），
    以及当前技能总数。测试与运维排查用。
    """
    skills, skipped = _scan_with_skips()
    return {"skills": skills, "skipped": skipped, "total": len(skills) + len(skipped)}


def get_skipped() -> list:
    """返回最近一次 list_skills() 扫描中被跳过的（损坏/无 frontmatter）文件相对路径。"""
    return list(_last_skipped)


def normalize_contract(item: dict) -> dict:
    """把任意技能 dict（folder 或 T6 DB 来源）补齐为 LibreChat 字段契约。

    仅做安全默认填充，不删除既有字段；供 /api/skills/list 合并端点统一收口。
    """
    it = dict(item)
    it.setdefault("name", it.get("title") or it.get("id") or "")
    it.setdefault("description", "")
    it.setdefault("trigger", "")
    it.setdefault("risk", "low")
    it.setdefault("allowed_tools", [])
    it.setdefault("version", "1.0.0")
    it.setdefault("category", it.get("toolset") or "general")
    it.setdefault("tags", [])
    return it


def load_skill(name: str):
    """按 name 取单个技能完整信息；不存在返回 None。"""
    for s in _scan_with_skips()[0]:
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
