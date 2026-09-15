"""专家系统：运行时注册表，供 WorkBuddy 式左侧「专家」菜单调用。

不改动 core/db.py（三指纹红线），运行时 CREATE TABLE IF NOT EXISTS。
初始内置一批与 MiniYuxi 业务场景匹配的专家角色。
"""
from __future__ import annotations

import json
from . import db

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS experts_registry (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

BUILTIN = [
    {
        "id": "hr-general",
        "name": "HR 人事专家",
        "description": "员工关系、制度起草、劳动争议程序与风险研判",
        "system_prompt": "你是一位资深 HR 与员工关系专家，熟悉中国大陆劳动法、深圳地方口径及企业人事实务。回答需给出可执行步骤、风险提示与适用法条索引。",
        "tags": "人事,法律,风险",
    },
    {
        "id": "legal-contract",
        "name": "合同合规专家",
        "description": "审合同、抓风险点、输出修改建议",
        "system_prompt": "你是一位合同与合规专家，擅长识别合同中的权利义务不对等、违约责任、争议解决与合规缺口，回答用 diff/表格形式给出修改建议。",
        "tags": "法务,合同",
    },
    {
        "id": "recruiter",
        "name": "招聘顾问",
        "description": "JD 撰写、人才画像、渠道与面试设计",
        "system_prompt": "你是一位招聘顾问，能基于岗位需求输出结构化 JD、人才画像、面试问题与渠道建议。",
        "tags": "招聘",
    },
    {
        "id": "excel-master",
        "name": "Excel 表格专家",
        "description": "公式、透视表、数据清洗与报表自动化",
        "system_prompt": "你是一位 Excel/WPS 表格专家，回答需给出可直接使用的公式、操作步骤或 Python 等价实现。",
        "tags": "办公,数据",
    },
    {
        "id": "coding-agent",
        "name": "Coding Agent",
        "description": "代码生成、重构、测试与代码审查",
        "system_prompt": "你是一位全栈开发专家，回答需给出可直接运行的代码片段、测试用例与关键注释。",
        "tags": "代码,开发",
    },
    {
        "id": "agent-architect",
        "name": "Agent 架构师",
        "description": "AI Agent 系统设计、工作流编排与多 Agent 协作",
        "system_prompt": "你是一位 AI Agent 平台架构师，擅长状态机、工具注册表、MCP 连接、记忆层与多 Agent 协作设计。",
        "tags": "AI,架构",
    },
]


def init(conn=None) -> None:
    c = conn or db.connect()
    c.execute(TABLE_SQL)
    if not conn:
        c.commit()


def _seed(tenant_id: str = "default") -> None:
    """幂等初始化内置专家。"""
    try:
        conn = db.connect()
        init(conn)
        existing = {r["id"] for r in conn.execute("SELECT id FROM experts_registry WHERE tenant_id=?", (tenant_id,)).fetchall()}
        for e in BUILTIN:
            if e["id"] in existing:
                continue
            conn.execute(
                "INSERT INTO experts_registry(id,tenant_id,name,description,system_prompt,tags) VALUES(?,?,?,?,?,?)",
                (e["id"], tenant_id, e["name"], e["description"], e["system_prompt"], e["tags"]),
            )
        conn.commit()
    except Exception:
        pass


def list_experts(tenant_id: str = "default", limit: int = 100) -> list[dict]:
    _seed(tenant_id)
    try:
        conn = db.connect()
        rows = conn.execute(
            "SELECT id,name,description,system_prompt,tags FROM experts_registry WHERE tenant_id=? ORDER BY id LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_expert(expert_id: str, tenant_id: str = "default") -> dict | None:
    _seed(tenant_id)
    try:
        conn = db.connect()
        row = conn.execute(
            "SELECT id,name,description,system_prompt,tags FROM experts_registry WHERE id=? AND tenant_id=?",
            (expert_id, tenant_id),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
