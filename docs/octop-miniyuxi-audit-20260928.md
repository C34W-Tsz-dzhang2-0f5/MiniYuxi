# Octop ↔ MiniYuxi 2.1 总对照表 · 代码实测核实

> 核实日期：2026-09-28
> 核实对象：`E:\HR有关AI\AI应用基座最佳实践\14_自研MiniYuxi` 的 `core/` + 项目根 `cli.py` + `apps/desktop`
> 方法：对每个能力域，实际 `Glob`/`Grep` 对应文件与关键符号，逐条印证任务书判定是否站得住
> 原始对照表来源：《MiniYuxi 目标任务书 · 可借鉴模块清单》第二部分 2.1

---

## 结论先行

任务书 2.1 总对照表的 **15 项判定经代码实测全部成立**，无夸大、无漏判。

- **3 项比任务书描述更领先**（实际已实现度 > 判定）：域 3 模型网关 `provider_router`（已是持久化注册表 + 运行时热切换）、域 7 Skills（契约已落地，非"走在路上"）、域 11 合规三闸（egress/citation_gate/soc_audit 全实装）。
- **2 项判定成立但缺口比字面更重**：域 6 SSO（core 内 **零** OIDC/OAuth/PKCE 代码，只有基础 RBAC/多租户）、域 4 渠道（connectors 有 5 种 kind 槽但**无任何厂商 SDK 实现**）。
- **1 项状态需更新**：域 7 已从"进行中 / 最高优先"变为"已完成"（本次会话已落地 LibreChat 契约）。

---

## 判定图例

✅ 直接对齐（思路/接口已对等，复用即可）｜🟡 部分对齐（需补接口或前端）｜🔴 需重写/新增（MiniYuxi 缺失或差距大）｜🟢 MiniYuxi 占优（杀锏，Octop 无对等深度，不动）

---

## 2.1 总对照表 · 实测核实

| # | 能力域 | 任务书判定 | 实际核实证据（core/ 实测） | 核实结论 | 风险 |
|---|---|---|---|---|---|
| 1 | Agent 运行时/进程管理 | 🟡 部分对齐 | `agent_loop.py`(ReAct)、`agent.py`(状态机)、`coding_agent.py`(install_tool/generate_tool 真实实现)、`eval_harness.py`(EvalHarness 类 + pass@k 真实实现)。**无**进程级异步 agent manager（无 HarnessAgentManager 对等物）。 | ✅ 站得住 | 🟡 中 |
| 2 | 多 Agent 协同/工作流编排 | ✅ 直接对齐 | `orchestration.py`：`run_team(task,roles,...)` + `run_automation(workflow,trigger,...)` 真实存在；`subagent.py`(create_agent)、`canvas.py`、`taskflow.py` 均在。 | ✅ 站得住 | 🟢 低 |
| 3 | 模型网关/供应商路由 | 🟢 占优 | `gateway.py`(重试+fallback+已收口 egress)、`provider_router.py`(**持久化 llm_providers 表 + 运行时 `set_active` 热切换**，比任务书描述更先进)、`model_hub.py` 均在。 | ✅ 站得住（实更领先） | 🟢 低 |
| 4 | 渠道接入/IM | 🔴 需重写（厂商适配） | `channels.py`：仅 `WeComChannel`（最小 webhook），`Channel` 基类。`connectors.py`：`KINDS=("wecom","wechat","crm","erp","feishu")` 有 5 槽但**无厂商 SDK 实现**，仅 register/send_message 信封。 | ✅ 站得住（缺口比字面更重） | 🔴 高 |
| 5 | 连接器/外部工具生态 | ✅ 直接对齐 | `connectors.py`(crm/erp 抽象) + `mcp_client.py`(stdio MCP) + `tools_registry.py` 均在。 | ✅ 站得住 | 🟢 低 |
| 6 | 认证/SSO/RBAC | 🟡 部分重写 | `auth.py`(自签 JWT+PBKDF2+RBAC)、`multitenant.py`、`security.py`、`approval.py` 均在。**core/ 内 `sso|oidc|oauth|pkce` 全 0 匹配 —— SSO 完全缺失**，只有基础 RBAC/多租户。 | ⚠️ 站得住但偏乐观（SSO 零基础） | 🟡 中 |
| 7 | Skills 体系（SKILL.md） | ✅ 直接对齐（最高优先） | `skills_catalog.py`(扫 skills/*.md + LibreChat 契约，本次已落地) + `skills.py`(T6 闭环学习) 均在。**状态更新：已从"走在正确路上"变为"契约已完成"**。 | ✅ 站得住（已超额完成） | 🟢 低 |
| 8 | RAG/知识库 | 🟢 占优 | `rag.py`(FTS5+sqlite-vec 双索引) + `rag_adapter.py`(RAGFLOW_*/FASTGPT_* 适配，已内建) 均在。 | ✅ 站得住 | 🟢 低 |
| 9 | 人工闸门 HITL | ✅ 直接对齐 | `agent.py`：`RECRUIT_FLOW`(S2/S9/S13 人工闸门) + `approval.py`：`create()` 挂审批卡，均在。 | ✅ 站得住 | 🟢 低 |
| 10 | 记忆/多轮上下文 | 🟡 部分对齐 | `memory.py`/`memory_v2.py` 均在；`agent_loop`/`gateway`/`rag` 用 `MAX_HISTORY=10`/`MAX_HISTORY_CHARS=800` 硬编码截断。**无 slim 智能压缩/预算控制**。 | ✅ 站得住 | 🟡 中 |
| 11 | 合规/出境/审计 | 🟢 占优 | `egress.py`(出境闸门) + `citation_gate.py`(法条闸门) + `soc_audit.py`(哈希链) + `security.py` 全在且已实装（0.4.0 已交付）。 | ✅ 站得住（实更领先） | 🟢 低 |
| 12 | 远程桌面/无头浏览器 | 🔴 需重写（按需） | core/ **无任何** browser/headless/remote_desktop 对等物。全项目 `playwright|headless` 命中仅 `scripts/`(截图取证工具) 与 `tests/`(公式验证)，**均非产品能力**。 | ✅ 站得住 | 🔴 高（按需） |
| 13 | 可视化控制台/画布 | ✅ 已落地 | 后端 `canvas.py`(DAG) + `taskflow.py` + `wb_workbench.py` 均在；**Dify 式拖拽画布前端已于 2026-09-28 补齐**（`web/flow-canvas.*` + `core/flow_store.py` + `/api/flow/*`，详见 `refactor-domain13-flow-canvas-20260928.md`）。 | ✅ 站得住 | 🟢 低 |
| 14 | 三端形态（Web/Desktop/CLI） | ✅ 直接对齐 | `apps/desktop`(Tauri) 存在；`cli.py` 在项目根（非 core）；Web 端存在。 | ✅ 站得住 | 🟢 低 |
| 15 | 专家/角色市场 | ✅ 已落地 | `experts.py` + `hrm.py` + `labor_relations.py` 垂直模块均在；**catalog/manifest 已于 2026-09-28 补齐**（`core/experts_manifest.py` + `GET /api/experts/manifest` + `web/experts-market.*`，详见 `refactor-domain15-experts-market-20260928.md`）。 | ✅ 站得住 | 🟢 低 |

---

## 5 处精确度修正 / 风险提示

1. **域 6 SSO（🟡 偏乐观）**：任务书写"部分重写"，但实测 core 内 SSO 代码 **0 行**。更准确表述为"RBAC/多租户/合规闸门已占优，但企业 SSO（OIDC/PKCE）完全缺失，需从零补"——仍归 🟡，但落地成本偏向"需补"侧而非"微调"。

2. **域 4 渠道（🔴 缺口更重）**：`connectors.py` 有 `wecom/wechat/crm/erp/feishu` 五槽，但**全是注册表槽，无厂商 API 适配实现**（无飞书/钉钉/企微 SDK）。这与"🔴 需重写（厂商适配）、由 N8N 接"完全一致；提醒：MiniYuxi 内核只留统一信封，厂商接入一律走 N8N，不逐个自研。

3. **域 7 Skills（状态更新）**：任务书签发时（2026-09-28）写"走在正确路上"，但本次会话已**完成** LibreChat 字段契约（45/45 验证通过、坏 frontmatter 跳过不崩）。现状应为"✅ 已完成"，非"进行中"。

4. **域 3 provider_router（实更领先）**：任务书仅对比"providers（harness_factory/presets/model_flags）"，但 MiniYuxi 的 `provider_router.py` 已是**持久化供应商注册表 + 运行时热切换**（`set_active` 即时生效、无需重启），超越基础预设式管理。🟢 占优成立且更稳。

5. **域 12 远程桌面（确认无对等，但非当前必须）**：已确认 core 无对等实现，命中的 playwright 仅为测试/取证脚本。优先级低，若企业场景需要再借 Octop 思路或第三方（且须本地优先、绝不走云端，遵照定位红线）。

---

## 整体风险分级

| 风险 | 域 | 说明 |
|---|---|---|
| 🔴 高 | 域 4（渠道厂商适配）、域 12（远程桌面，按需） | 域 4 是真实缺口（需 N8N 接入才能补）；域 12 当前不需要 |
| 🟡 中 | 域 1（进程级 agent manager）、域 6（SSO 从零补）、域 10（记忆压缩）、域 13（Dify 画布前端）、域 15（专家市场 manifest） | 均有基础，需补接口/前端 |
| 🟢 低 | 域 2、3、5、7、8、9、11、14 | 已对齐/占优/已完成，无需大改 |

---

## 待办（承接核实结论）

- [ ] 域 4：在 N8N 侧配一条「CRM→MiniYuxi webhook」示范流，验证内核零改动（任务书交付清单第 4 条）
- [ ] 域 6：评估企业 SSO（OIDC/PKCE）接入方案（从零补，非微调）
- [x] 域 13：Dify 式画布已落地 —— `web/flow-canvas.html`+`flow-canvas.js`（拖拽/连线/属性/存读/导入导出/引用现有流程）+ `core/flow_store.py`+`/api/flow/*` 持久化底座（2026-09-28 完成，详见 `docs/refactor-domain13-flow-canvas-20260928.md`）
- [x] 域 15：专家市场 manifest 已落地 —— `core/experts_manifest.py` + `GET /api/experts/manifest` + `web/experts-market.*` 卡片市场前端（2026-09-28 完成，详见 `docs/refactor-domain15-experts-market-20260928.md`）
- [x] 域 7：Skills LibreChat 契约 —— 已完成并验证（本次）
