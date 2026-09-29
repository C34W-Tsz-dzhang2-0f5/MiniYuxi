# MiniYuxi SKILL.md 字段契约（对齐 LibreChat）

> 签发依据：《MiniYuxi 目标任务书 · 可借鉴模块清单》（Kazke，2026-09-28）· 任务 2
> 适用范围：`skills/**/SKILL.md`（指令层 Agent Skills）
> 加载器：`core/skills_catalog.py`
> 收口端点：`api.py` → `GET /api/skills/list`（folder 技能 + T6 闭环学习技能统一收口）
> 验收脚本：`tests/_verify_skills_contract.py`

---

## 0. 一句话定调

MiniYuxi 的指令层技能 **以 LibreChat 的 `SKILL.md` 规范为唯一基准**，统一 `skills/` 目录与
`core/skills_catalog.py` 的加载/隔离机制。技能正文作为 **user message 段注入**，不污染 system 主结构；
技能可被 **自动触发** 与 **权限约束**；损坏 frontmatter 一律 **跳过且不崩**。

---

## 1. 字段契约（强制项 + 扩展项）

| 字段 | 类型 | 必填 | 默认值 | 含义 / 取值 |
|---|---|---|---|---|
| `name` | string | ✅ | —（缺失=损坏，跳过） | 技能唯一 id；同时作为 UI 选中后的加载键，必须稳定可寻址 |
| `description` | string | ✅（建议） | `""` | 一句话能力说明；用于列表展示 + 注入清单 |
| `trigger` | string | 可选 | `""` | 自动触发词 / 场景；命中后按对应工作流执行 |
| `risk` | string | 可选 | `"low"` | 风险等级 `low` \| `medium` \| `high`；高风险后续接 HITL 人工闸门 |
| `allowed_tools` | list | 可选 | `[]` | 本技能允许调用的工具白名单；后续接 toolset 约束 |
| `version` | string | 可选 | `"1.0.0"` | 语义化版本（对齐 Octop 发布元数据） |
| `category` | string | 可选 | `toolset` 或 `"general"` | 分类；缺省取 `toolset`，再缺省 `general` |
| `tags` | list | 可选 | `[]` | 标签列表 |

### 兼容透传字段（不强制，但会被解析并保留）
- `toolset`：历史字段，作为 `category` 的别名来源（向后兼容）。
- `slug` / `display_name`：兼容 WorkBuddy 风格元数据，透传不进强制契约。

### 写入约定
- frontmatter 用 `---` 包裹；标量可用引号也可不用，`skills_catalog` 会自动剥引号。
- `allowed_tools` / `tags` 支持两种写法：YAML 列表 `[Read, Grep]` 或逗号串 `Read, Grep`。
- 块标量（`trigger` 等长文本）可用 `|` / `>`。

---

## 2. 模板（新技能请照抄）

```markdown
---
name: your_skill_id
description: 一句话说明这个技能能做什么
trigger: 用户提到「…」或进入「…」场景时
risk: low                # low | medium | high
allowed_tools: [Read, Grep, Edit]   # 工具白名单；不写默认 []
version: 1.0.0
category: hr             # 不写则取 toolset，再不写则 general
tags: [hr, compliance]
---

# 技能正文（作为 user message 段注入，不污染 system）

这里写技能的实际工作流、步骤、约束…
```

---

## 3. 加载与隔离机制（加载器行为）

`core/skills_catalog.py`：

1. **扫描**：递归 glob `skills/**/SKILL.md`。
2. **解析**：`_parse_frontmatter` 解析 YAML frontmatter（标量/块标量/列表）。
3. **损坏跳过**：无 frontmatter、缺 `name`、解析异常 → 进 `skipped` 列表，**不抛栈、不崩**。
4. **契约归一**：`_to_contract` 把 meta 映射到 §1 契约；缺省字段填默认。
5. **缓存**：按 `skills/` 目录 mtime 缓存（`list_skills`），UI 高频调用不反复扫盘。
6. **可观测**：`scan_skills()` 返回 `{"skills", "skipped", "total"}`；`get_skipped()` 取最近跳过的文件。
7. **注入**：`inject_text()` 生成「可用技能清单」user message 段（含 `trigger` 提示）。

### 双源合并（端点收口）
`/api/skills/list` 把 **folder 技能（`skills_catalog`）** 与 **T6 闭环学习技能（`core/skills.py` DB）**
合并为一张列表，统一过 `normalize_contract()` 补齐契约（无论来源均 100% 含 §1 字段）。

> 红线（任务书 §6）：`core/skills.py`（T6 对话经验沉淀）**逻辑不改动**，只在端点合并层收口。

---

## 4. 自动触发与权限约束（路线图）

- **自动触发**：`trigger` 字段被 `inject_text()` 注入对话上下文；命中关键词由 agent_loop 决定是否加载正文。
  —— 当前为「清单 + 提示」弱触发，强触发（自动调用）后续接入。
- **权限约束**：`allowed_tools` 为工具白名单雏形；与 `risk` 联动——
  `risk: high` 的技能后续默认挂 `approval.py` HITL 闸门（不自动执行敏感动作）。
- **出境收口**：任何技能若触发外部调用（LLM/外部 RAG/ERP/CRM），必须经 `core/egress.py`
  （任务书红线 ②），不在技能内直连第三方。

---

## 5. 验收（如何确认自己没写坏）

```bash
# 仓库根执行（纯标准库，无需额外依赖）
python tests/_verify_skills_contract.py
```

验收项：
1. folder 技能 100% 含契约标量字段（`name/description/trigger/risk/version/category`）；
2. folder 技能 100% 含契约列表字段（`allowed_tools/tags`）；
3. 路由合并（folder + T6）后整张列表 100% 契约补齐；
4. 坏 frontmatter 跳过且不崩（畸形输入 + 真实落盘坏文件双重验证）；
5. `inject_text()` 有技能时返回非空清单。

退出码 `0` = 全部通过；`1` = 有失败。

---

## 6. 存量迁移提示

仓库内存在两种历史格式，加载器均兼容、不强求改写：
- **MiniYuxi 旧式**：`name/description/trigger/toolset`（无 risk/allowed_tools/version）→ 缺省填默认，正常加载。
- **WorkBuddy 式**：`slug/version/displayName/category/tags`（无 name）→ **缺 name 会被判损坏跳过**；
  这类文件若想被 MiniYuxi 指令层加载，需补 `name` 字段（见 §2 模板）。

> 不强制一次性改写存量文件；新技能严格按 §2 模板即可保证 100% 契约。
