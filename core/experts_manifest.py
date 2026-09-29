"""M7 专家市场 manifest（域15 后端）：把已注册 Skills 聚合成可发布的"专家市场"清单。

设计：复用 skills_catalog.list_skills()（已对齐 LibreChat 契约），在其上叠加市场元数据
（license / author / icon / 分类聚合），产出 marketplace-ready manifest。
红线：不碰 agent.py/rag.py/db.py；本文件为新增。供 web/experts-market.* 市场前端消费。
"""
import time

from . import skills_catalog

_CATEGORY_ICON = {
    "hr": "👥", "legal": "⚖️", "finance": "💰", "law": "⚖️",
    "recruit": "🧲", "compliance": "🛡️", "office": "📄", "general": "🧩",
}


def _icon_for(category: str) -> str:
    return _CATEGORY_ICON.get((category or "").lower(), "🧩")


def _enrich(skill: dict) -> dict:
    name = skill.get("name") or ""
    category = skill.get("category") or "general"
    return {
        "id": name,
        "name": name,
        "display_name": skill.get("display_name") or name,
        "description": skill.get("description") or "",
        "trigger": skill.get("trigger") or "",
        "risk": skill.get("risk") or "low",
        "category": category,
        "tags": skill.get("tags") or [],
        "version": skill.get("version") or "1.0.0",
        "allowed_tools": skill.get("allowed_tools") or [],
        "license": "商用授权见 scripts/audit_licenses.py 台账",
        "author": "MiniYuxi Skills",
        "icon": _icon_for(category),
        "entrypoint": skill.get("path") or "",
        "size_chars": len(skill.get("body") or ""),
    }


def build_manifest() -> dict:
    """构建专家市场清单：聚合分类 + 逐个专家条目。"""
    skills = skills_catalog.list_skills()
    experts = [_enrich(s) for s in skills if s.get("name")]
    cats = {}
    for e in experts:
        cats.setdefault(e["category"], 0)
        cats[e["category"]] += 1
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(experts),
        "categories": [{"category": c, "count": n} for c, n in sorted(cats.items())],
        "experts": experts,
    }


def get_expert(expert_id: str):
    for e in build_manifest()["experts"]:
        if e["id"] == expert_id:
            return e
    return None
