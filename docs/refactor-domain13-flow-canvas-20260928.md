# 域13 改造：Dify 风格流程画布（前端 + 持久化底座）

> 任务书判定：🟡 需改造（控制台 / Dify 画布前端）。
> 优先级：P1（第一项）。落地日期：2026-09-28。
> 对标：Dify 可视化工作流画布；Octop 仅作反面参照（其本身无可视化画布）。

## 1. 现状核实（改造前）

- MiniYuxi **已有流程执行能力**，缺的是"可视化编排/创作"：
  - `core/agent.py`：`FLOWS = {"recruit": RECRUIT_FLOW}`（19 阶段、含 HITL 节点），经 `/api/agent/start|step|run` 执行。
  - `core/taskflow.py`：岗位任务流引擎（提示词解析 → 自动执行），经 `/api/taskflow/*`。
  - `web/wb_workbench.js`：`openFlowModal` 仅下拉选流程 + 启停，无节点图。
- **缺口**：用户无法可视化地设计/编辑一条流程，只能跑代码写死的 `recruit`。
- Octop 对照（已 clone 实读 `ref-octop`）：Octop 编排是代码/YAML 驱动（`run_team`/`run_automation`），
  **根本没有可视化画布**；`dashboard/` 是 React SPA 但无 node-editor/canvas 依赖。
  结论：MiniYuxi 此刻补齐画布后，在"可视化编排"维度**反超** Octop。Dify 才是画布的本尊参照。

## 2. 目标

给用户一个 Dify 风格的可视化画布：拖拽节点、连线、编辑属性、保存/载入/导出/导入，
并把画布编排存库（持久化底座）。同时支持"引用现有流程"把代码定义的 `recruit` 等挂为子流程节点。

## 3. 新增/改动文件（红线合规）

### 后端（additive）
- `core/flow_store.py`（新增）：`save_flow / list_flows / get_flow / delete_flow`，自建 `flows` 表
  （`CREATE TABLE IF NOT EXISTS`，复用 `db.connect()`，与 `memory.py` 同模式，**不触碰 db.py**）。
- `api.py`（additive）：新增 4 路由（均 `need("chat")`，不破坏现有）：
  - `POST /api/flow/save`、`GET /api/flow/list`、`GET /api/flow/{fid}`、`DELETE /api/flow/{fid}`。
  - 新增请求模型 `FlowSaveIn`。

### 前端（additive，纯静态，不碰 core 红线）
- `web/flow-canvas.html`：Dify 风格三栏布局（左节点面板 / 中 SVG 画布 / 右属性面板）+ 顶工具栏。
- `web/flow-canvas.js`：完整画布逻辑（平移/缩放/拖拽节点/端口连线/属性编辑/保存载入/导入导出/引用现有流程）。
- `web/wb_workbench.js`：`openFlowModal` 增加"可视化画布"按钮 → `window.open('/flow-canvas.html')`。

### 节点类型（Dify 风格）
`start / llm / tool / condition / human(HITL) / knowledge / flowref(引用现有流程) / end`。

## 4. 测试与验收

- `tests/_verify_flow_store.py`（5 项，离线内存库，全程绿 exit 0）：
  1. save/get　2. upsert（同 id 覆盖不增行）　3. 租户隔离　4. delete　5. 字符串/字典定义兼容。
- `py_compile` 通过：`api.py` + `core/flow_store.py`。
- `node --check web/flow-canvas.js` 通过（语法）。

### 过程中修掉的两个真 bug（flow_store）
1. **id 毫秒碰撞**：原 `flow_` + `int(time.time()*1000)` 在快速连存时同毫秒同 id，
   叠加 upsert 不改 `tenant_id` → 行被静默改主。改为 `uuid.uuid4().hex[:12]`（碰撞安全）。
2. **`Connection.rowcount` 不可靠**：`delete_flow` 返回 `c.rowcount` 在异常路径被吞成 0
   （实际已删除）。改为返回游标 `cur.rowcount`。

## 5. 红线自检（任务书 §6）

- [x] 未改 `agent.py` / `rag.py` / `db.py`（仅新增 `flow_store.py`；api.py 仅 additive 路由）
- [x] 无新增网络/LLM 调用（画布存取的都是本地 CRUD；LLM 执行沿用既有 `/api/agent/*`）
- [x] 前端为纯静态新增页，不碰 core
- [x] 测试离线可跑

## 6. 风险分级

| 项 | 等级 | 说明 |
|---|---|---|
| 画布编排出新图但未接运行时 | 🟡 中 | 本期只做"可视化编排 + 持久化 + 引用现有流程"，**画布新图自动执行需后续接运行时**（可复用 agent.py 阶段模型或新执行器）；标注为 follow-up |
| 现有流程内部节点不可见 | 🟢 低 | `list_flows` 仅暴露 stage 数/HITL，故"引用现有流程"做成 flowref 子流程节点，不臆造内部图 |
| 前端未接自动化测试 | 🟢 低 | 纯静态页；已 `node --check` + 后端全绿，UI 需人工验收 |

## 7. Octop 对照（实读 ref-octop 后）

- Octop：`src/octop/infra/agents/experts/...` 是专家库；编排为代码/YAML，**无 visual canvas**；
  `dashboard/` React SPA 无 node-editor 依赖。
- MiniYuxi：本期补齐 **Dify 风格可视化画布 + 持久化底座**，在"可视化编排"维度领先 Octop；
  执行侧沿用既有 HITL + taskflow，成熟稳定。

## 8. 交付清单

- [x] `core/flow_store.py`（+ 修 2 bug）
- [x] `api.py` 4 路由 + `FlowSaveIn`
- [x] `web/flow-canvas.html` / `web/flow-canvas.js`
- [x] `web/wb_workbench.js` 入口按钮
- [x] `tests/_verify_flow_store.py`
- [x] 本方案文档
- [ ] follow-up：将画布新图接入运行时（可选，非本期范围）
