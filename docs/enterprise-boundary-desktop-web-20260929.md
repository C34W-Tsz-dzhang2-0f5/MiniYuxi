# MiniYuxi 桌面版 + 网页版 · 企业级生产边界定义（定边界）

> 工具：`enterprise-agent-scaffolding`（vibe-coding-workflow 的 S-前置「定生产边界」步骤）
> 日期：2026-09-29
> 衔接：
> - `vibe-coding-workflow` 七阶段已于今日跑过审计（见 `docs/vibe-coding-audit-miniyuxi-20260929.md`，S0/S1/S2/S4 达标、S3 已整改、S5/S6 收口）。
> - 本文件是「定边界」产出，并 **纠正/重框** `docs/企业级合规与架构边界说明.md`（2026-09-14）的「多租户 SaaS + 对外高并发 HA」假设。
> - 后续 S0 基础设施由 `setup-matt-pocock-skills` 落地（见任务 #2）。

---

## 0. 定位重申（边界的前提，最高优先级）

据阿长 2026-09-24 更正的产品定位（覆盖此前一切表述）：

> **MiniYuxi = 企业级 Agent · 零 Docker · 数据可出本机 · 可商用。**

三端形态与底座：

| 表面 | 形态 | 底座 | 多租户 |
|---|---|---|---|
| **桌面版** | Tauri 壳 + 本机单进程 | 单用户、单 SQLite 文件 | ➖ **天然单租户**（本机单人） |
| **网页版** | 复用 `web/` | 可本机跑，也可对外部署 | 🟡 取决于部署形态（单机/内网单租户 ↔ 对外多租户） |
| **共用 core** | `core/` Python | 三端外壳只做传输，业务全在 core | 隔离闸门在 core，HA 在外 |

**关键区分（本文件的边界核心）**：旧文档把「多租户 SaaS + 对外高并发 HA」当默认假设，得出一堆「需外部基础设施」结论。但 MiniYuxi 实际是 **零 Docker 桌面优先** 产品——

- **桌面版**：多租户隔离、负载均衡、读写分离、对外 HA **➖ 不适用**（本机单用户单进程）；
- **网页版**：只有当它被**对外多租户部署**时，才需要叠加 ① 多租户隔离 / ② RBAC / ④ 可观测面板 / ⑧ canary；若仅本机或内网单租户跑，则与桌面版同门禁。

因此八要素必须**分表面定边界**，不能一刀切。

---

## 1. 八要素 × 分表面边界矩阵

图例：✅ 已达标 · 🟡 部分（有骨架/跟踪，缺强制或全覆盖）· 🔴 缺口（上生产前必补）· ➖ 不适用

| # | 要素 | 桌面版 | 网页版（对外多租户） | 当前实现（core） | 证据 | 边界决策 |
|---|------|:---:|:---:|---|---|---|
| **1** | 多租户隔离 | ➖ N/A | 🔴 必做（DB/schema/RLS + 请求级注入） | `multitenant.enforce` 配额/驻留/MLPS/CMK 闸门 + `readiness` 账本（仍单库） | `core/multitenant.py` | 桌面：无需；网页对外：必须数据层隔离 + 每次请求注入 tenant，agent 不得"记"上一租户；连接器凭证按 tenant 隔离 |
| **2** | IAM / 最小权限 | 🟡 连接器令牌最小权限 + 工具风险分级 | 🔴 需 RBAC 矩阵 + task-scoped 短效令牌 + 用户身份贯穿 tool call | `auth.py`（Token TTL 身份鉴别）、`approval.py` 风险集、`security.py` 脱敏 | `core/auth.py` `core/approval.py` `core/security.py` | 桌面：连接器令牌按任务最小权限、严禁长期宽泛；网页对外：补 RBAC + 短效令牌；读写工具分离（起草/发送是两个工具） |
| **3** | 审计日志 | ✅ | ✅ | `soc_audit` 结构化事件 + **哈希防篡改链**；egress 进链 | `core/soc_audit.py` `core/egress.py` | 两表面共用，已达标；保持 PII 脱敏落日志（egress 已做） |
| **4** | 可观测性 / Tracing | 🔴 **全缺** | 🔴 **全缺** | 全仓 `grep` trace_id/span/metrics/observ **0 命中** | `core/*`（无） | **真缺口**：需端到端 trace（retrieval→tool→action，带时间戳+成本）+ 指标（成功率/延迟/单次成本/升级率）。门禁：上生产前至少补 `trace_id` 贯穿 + 成本指标导出 |
| **5** | 成本控制 / 熔断 | 🟡 跟踪有、硬限缺 | 🟡 同 | `usage.py` 记每次 LLM/Embedding token 与成本（人民币估算） | `core/usage.py` | **桌面商用按席位计费 → 硬预算上限 + `maxSteps` + 失控循环熔断必须补**；门禁：无步数/超时/token 上限 = 失控循环事故 |
| **6** | HITL / 不可逆拦截 | ✅ 应用内审批卡 | ✅ 同 | `approval` 状态机 pending→approved/rejected + `resume_token`；`ASK_EVERY_TIME` 含 `agent.run/tenant.manage/user.manage/kb.delete/mcp.write/kb.upload` | `core/approval.py` | 两表面共用；门禁：发消息/删数据/转账等不可逆动作独立人审，**不得模型自审** |
| **7** | 行为评测集 | 🟡 harness 有 | 🟡 同 | `eval_harness`（YAML 任务 + Pass@1/k + LLM-as-Judge）；技能安装 49 项 + e2e 7/7 | `core/eval_harness.py` `tests/` | 补标注**对抗集**（prompt injection / 畸形输入 / 工具不可用 / 冲突数据）；门禁：发布前跑 eval + 阈值 |
| **8** | CI/CD 与灰度 | 🟡 MSI 重出 + CI 闸门 | 🟡 `verify.yml` + 版本一致性 | 本地+CI 闸门 6/6 绿；桌面 MSI（WiX）重出 | `.github/workflows/verify.yml` | 桌面无 canary（本机 MSI），回滚=重装旧版；网页对外需 canary + 回滚预案 |

### 现状小结（证据来自今日实盘 `grep` / `git` / 模块头）
- **已稳（✅）**：③ 审计（SOC 哈希链）、⑥ HITL（审批卡+断点续跑）。
- **有骨架待强制（🟡）**：① 隔离闸门（非数据层）、② IAM（鉴别有、RBAC 无）、⑤ 成本跟踪（非熔断）、⑦ 评测 harness（非对抗集）、⑧ CI（非 canary）。
- **真缺口（🔴）**：④ **可观测性完全缺失**；⑤ **成本硬熔断缺失**；网页对外时 ①/② 升级为 🔴。

---

## 2. 与旧「企业级合规与架构边界说明.md」的关系

- **保留**其「代码控制点 vs 外部依赖」结论：等保三级 / ISO 27001 / CMK / HA 的**证书与基础设施仍须外部**（测评机构、认证机构、KMS/HSM、负载均衡+托管库），任何代码平台替代不了。
- **纠正适用面**：旧文档默认「多租户 SaaS + 对外高并发」，把 ①/②/④/⑧ 当成普遍硬约束。本文件判定——MiniYuxi 是**零 Docker 桌面优先**产品，**桌面版 ① 多租户 / 对外 HA 天然 ➖ N/A**；只有「网页版对外多租户部署」形态才需叠加 ①/②/④/⑧。
- **未变**：③ 审计、⑥ HITL、商用授权（零 copyleft，见 `scripts/audit_licenses.py` 已审 126 包）对所有表面都是硬门禁。

> 一句话：旧文档给的是「云 SaaS 形态」的合规地图；本文件给的是「桌面优先、网页可部署」形态下**真正要卡的生产边界**。

---

## 3. 上生产门禁（分表面）

### 桌面版（0.5 及以后）门禁
- ✅ **已过**：审计（SOC 哈希链）、HITL（审批卡）、商用授权审计（126 依赖零 copyleft）、MSI 干净装机验证、`_e2e_browser_skill_install.py` 7/7、`_verify_skill_install_and_video.py` 49/49、CI 闸门 6/6。
- 🔴 **必补（否则禁上生产）**：
  - **④ 可观测性**：`trace_id` 贯穿 retrieval→tool→action，至少导出成功率/延迟/单次成本/升级率；
  - **⑤ 成本硬熔断**：per-run/per-tenant/per-user 预算硬上限 + `maxSteps` + `timeoutMs` + 失控循环自动熔断+告警。
- 🟡 **建议**：⑦ 补对抗评测集（注入/畸形/工具不可用/冲突数据）。

### 网页版门禁（仅当**对外多租户部署**）
- 在桌面版门禁基础上**叠加**：① 多租户数据隔离（DB-per-tenant 或 schema + 请求级注入）；② RBAC + 短效令牌 + 用户身份贯穿；④ 可观测指标面板；⑧ canary + 回滚预案。
- 若网页版仅本机/内网**单租户**跑 → 与桌面版同门禁（①/②/④/⑧ 不升级）。

---

## 4. 风险分级

| 级别 | 事项 | 敞口 |
|---|---|---|
| 🔴 高 | ④ 可观测性全缺 + ⑤ 成本硬熔断缺 | 桌面版**商用按席位计费**，失控循环/成本爆雷即直接事故；网页对外若无 ① 隔离 = 越权/串数据事故 |
| 🟡 中 | ② 网页版 RBAC 未补；⑦ 对抗评测集未成体系 | 过程正确结果错误的 agent 漏检；网页多用户越权 |
| 🟢 低 | ③ 审计、⑥ HITL、⑧ 桌面 CI 已稳；商用授权已审零 copyleft | — |

---

## 5. 下一步（衔接 vibe-coding-workflow S0 基础设施）

1. **S0 落地**：跑 `setup-matt-pocock-skills` 建 `CONTEXT.md`（先把 **桌面版 / 网页版 / 共用 core** 三表面的共享术语钉死，防语义扩散）+ `docs/agents/issue-tracker.md` + `docs/adr/`。
2. **第一批 tracer-bullet 工单**（走 `to-spec` → `to-tickets` → `implement`）：
   - 工单 A：**④ 可观测性 `trace_id` 贯穿**（core 调用链打点 + 成本指标导出）；
   - 工单 B：**⑤ 成本硬熔断**（`maxSteps`/`timeoutMs`/预算上限/失控循环熔断，接 `usage.py`）。
3. **ask-matt 路由结论**（详见任务 #3）：本任务属 **multi-session build** → `grill-with-docs`（在 CONTEXT.md 沉淀）→ `to-spec` → `to-tickets`（按 frontier 无阻塞优先）→ `implement`（每票 `/tdd` + `/code-review`）→ S4 真实回归 → S5 并行评审（Jev 八维）→ S6 固化成 skill。

> ⚠️ 附：本地 `main` 已 12 提交但 `origin/main [gone]`——审计里的 14 提交整改**从未 push**。定边界与 S0 落地后，应先将 `main` 推到远端（ghfast.top 镜像）或确认远端分支，避免本地工作无远端兜底。
