# 域15 改造：专家市场 manifest（Skills → 可发布市场清单）

> 任务书判定：🟡 需改造（专家市场 manifest）。
> 优先级：P1（第二项，P1 收尾）。落地日期：2026-09-28。
> 对标：Octop `infra/agents/experts/library`（专家库，但无统一市场 manifest API）；Dify/WorkBuddy 市场形态。

## 1. 现状核实（改造前）

- `core/skills_catalog.py`（目标任务书 §2 域7 已落地，45/45 契约全覆盖）：扫描 `skills/` 下所有 `SKILL.md`，
  归一为 LibreChat 字段契约（name/description/trigger/risk/version/category/tags/allowed_tools…）。
- **缺口**：契约只服务于"注入对话 / 列表展示"，**没有市场发布形态**——一个聚合的、带分类/授权/版本的市场清单，
  以及可浏览的市场前端。
- Octop 对照（实读 `ref-octop`）：`src/octop/infra/agents/experts/library/*` 是专家库（含 cvm-ai-doctor、office-automation 等），
  **但无统一的市场 manifest API**；MiniYuxi 把已归一化的 45 个技能直接聚合成市场清单，反而更规整。

## 2. 目标

把已注册的 Skills 聚合成 marketplace-ready 的"专家市场"清单（分类聚合 + 市场元数据：icon/license/author/version/risk），
并提供可浏览的前端（卡片网格 + 分类筛选 + 搜索 + 详情），工作台新增"专家"入口。

## 3. 新增/改动文件（红线合规）

### 后端（additive）
- `core/experts_manifest.py`（新增）：`build_manifest()` 复用 `skills_catalog.list_skills()`，逐个 enrich 市场字段
  （icon 按分类映射 emoji、license/author 默认、risk 透传），并聚合 `categories`；`get_expert(id)` 单查。
- `api.py`（additive）：新增 `GET /api/experts/manifest`（`need("chat")`），返回 `build_manifest()`。

### 前端（additive，纯静态）
- `web/experts-market.html`：轻主题卡片网格 + 顶栏搜索 + 分类 chips + 右侧详情抽屉。
- `web/experts-market.js`：消费 `/api/experts/manifest`，分类筛选 + 关键词搜索 + 详情，token 感知。
- `web/wb_workbench.js`：NAV_ITEMS 增加 `{ label:'专家', action:'experts' }` + 分支 `window.open('/experts-market.html')`。

## 4. 测试与验收

- `tests/_verify_experts_manifest.py`（5 项，离线扫描真实 skills/，全绿 exit 0）：
  1. manifest 结构（generated_at/count/categories/experts）　2. 每个专家字段完整（含 icon/license/risk）
  3. 分类聚合之和==count　4. get_expert 命中/未命中　5. manifest 计数 == skills_catalog 计数（=45）。
- `py_compile` 通过：`api.py` + `core/experts_manifest.py` + `flow_store.py` + `memory_slim.py`。
- `node --check web/experts-market.js` 通过。
- 回归：`_verify_skills_contract.py` 仍 45/45（api.py 新增 import/路由未影响 /api/skills/list 合并）。

## 5. 红线自检（任务书 §6）

- [x] 未改 `agent.py` / `rag.py` / `db.py`（仅新增 `experts_manifest.py`；api.py 仅 additive 路由）
- [x] 无新增网络/LLM 调用（只读本地 skills 目录）
- [x] 前端为纯静态新增页，不碰 core
- [x] 测试离线可跑，复用真实 skills/ 数据

## 6. 风险分级

| 项 | 等级 | 说明 |
|---|---|---|
| license/author 为默认占位 | 🟢 低 | 真实授权台账在 `scripts/audit_licenses.py`；manifest 标注来源，不臆造 |
| 市场仅"浏览"，未做上架/交易 | 🟢 低 | 本期范围是"manifest + 浏览"，上架/版本发布为 follow-up（任务书"发布机制"） |
| 前端未接自动化测试 | 🟢 低 | 纯静态页；已 `node --check` + 后端全绿，UI 需人工验收 |

## 7. Octop 对照（实读 ref-octop 后）

- Octop：`infra/agents/experts/library/*` 是专家库目录（cvm-ai-doctor、office-automation…），
  **无统一市场 manifest API**；MiniYuxi 把 45 个已归一化技能直接聚合成市场清单，形态更规整、可发布性更强。

## 8. 交付清单

- [x] `core/experts_manifest.py`
- [x] `api.py` `GET /api/experts/manifest`
- [x] `web/experts-market.html` / `web/experts-market.js`
- [x] `web/wb_workbench.js` 入口（NAV + 分支）
- [x] `tests/_verify_experts_manifest.py`
- [x] 本方案文档
- [ ] follow-up：专家上架/版本发布机制（非本期范围）
