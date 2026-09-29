# ACP 委派架构设计文档 评审（Octop + MiniYuxi 整合方案）

> 评审对象：`ACP 委派架构企业部署拓扑与权限审计设计.html`（v1.0，2026-09-29 生成，1.5MB，内部技术评审稿）
> 评审基准：MiniYuxi 0.4.0 实际代码栈（`requirements.txt` / `core/` 实测）+ 企业级 Agent 定位（零 Docker / 数据可出本机 / 可商用）
> 关联文档：`docs/octop-miniyuxi-audit-20260928.md`（此前 Octop 对比审计）

## 0. 一句话结论

这份文档在**架构层**（ACP 双向委派、RBAC、全链路审计）画得对，但在 **MiniYuxi 的技术栈与部署形态**上写了两套不存在的东西——它假设 MiniYuxi 跑 **LangGraph + LightRAG + Milvus + PostgreSQL + MinIO 的 Docker 多节点多租户**，而现实是 **FastAPI + sqlite-vec 本地向量 + FTS5/BM25、零 Docker、桌面优先的单租户**。按文档原样落地会推翻 MiniYuxi 的产品底座。

⚠️ **最关键冲突**：文档的部署与隔离全篇依赖 Docker 容器沙箱（2.4 / 3.4 / 部署清单），而「零 Docker」是 MiniYuxi 的硬定位红线（已写进 `pyproject.toml` 描述）。二者不可调和，必须二选一。

**可采纳的**：它的**抽象安全设计**——审计字段表（13 字段）、4 级风险分级、ACP 权限透传 5 步——可直接并入 MiniYuxi 已建的 8 要素（egress / SOC / HITL / cost-breaker / observability），低成本高收益。

---

## 1. 文档内容速览（它到底说了什么）

| 章节 | 核心内容 |
|---|---|
| 一、部署拓扑 | 5 层：用户接入层（Web / Electron / 飞书企微 IM / Cron / 开放 API）→ Octop 主调度层（harness-agent）→ ACP 桥接层（双向）→ MiniYuxi 知识子 Agent（ACP Runner）→ 数据存储层 → 安全监控横切层。数据流：蓝=用户请求→Octop，黄虚=Octop→ACP，绿=ACP→MiniYuxi，紫虚=数据层读写，橙虚=安全审计横切。 |
| 二、权限设计 | 四层模型：统一鉴权 + 细粒度 RBAC + 工作空间隔离 + 数据权限透传。5 角色（超级管理员 / 业务管理员 / 普通用户 / 只读访客 / 系统服务账号）+ 10 模块权限矩阵。 |
| 三、审计合规 | 全链路 trace_id 串联（用户→Octop→ACP→MiniYuxi→工具→文件）；13 字段审计标准；4 级风险（低/中/高/严重）响应策略；合规 checklist（TLS1.2+ / AES-256 / 留存≥180 天 / 双写）。 |
| 四、落地清单 | 8 步：基础设施 → 部署 Octop → 部署 MiniYuxi → 开发 ACP 桥接 → 接入 Octop ACP → 权限审计联调 → 压测灰度 → 正式上线。 |

---

## 2. 与 MiniYuxi 实际底座的冲突清单（核心）

| # | 维度 | 文档假设 | MiniYuxi 现实（0.4.0） | 冲突 | 等级 |
|---|---|---|---|---|---|
| C1 | 部署形态 | Docker Compose 多节点；容器级隔离（2.4 / 3.4 / 部署清单） | 零 Docker，桌面 / 单机优先（`pyproject.toml` 描述） | 推翻产品底座 | 🔴 高 |
| C2 | 向量 / 检索栈 | Milvus 向量库 + 知识图谱可视化 | `sqlite-vec`（纯 C，无服务进程）+ FTS5 / BM25（`requirements.txt`） | 虚构重度基础设施 | 🔴 高 |
| C3 | 主数据库 / 文件 | MiniYuxi PostgreSQL + MinIO 文件存储 | 本地 SQLite（`core/db.py`）；无 PG / MinIO | 虚构 | 🔴 高 |
| C4 | 编排引擎 | LangGraph 编排 + LightRAG 图谱引擎 | 自研 `core/agent_loop.py` + `core/rag.py`；无 LangGraph / LightRAG 依赖 | 虚构 | 🟡 中 |
| C5 | 租户模型 | 5 角色 RBAC + 部门数据隔离 + SSO/OIDC 多租户 | 当前单用户桌面（`admin/admin123`）；`core/auth.py`、`core/multitenant.py` 有雏形但非 Docker 多租户 | 定位错位，需决策 | 🟡 中 |
| C6 | 产品角色 | MiniYuxi = Octop 的「知识子 Agent」 | 定位是「企业级 Agent」（自主底座，非子模块） | 叙事降格 | 🟡 中 |
| C7 | 数据出境 | Octop 主调度经 ACP 拉取 MiniYuxi 检索结果 | 已有 `core/egress.py` 收口所有出境；ACP 桥接为新组件，须过闸 | 可合规，但需接线 | 🟢 低 |

> **重要提示**：C2 / C3 / C4 不是「还没做」，而是**文档对 MiniYuxi 内部实现的错误想象**——作者显然没看过 `requirements.txt` 和 `core/`。这点在对 Octop 侧沟通时要先澄清，否则对方会按错误前提写集成代码。

---

## 3. 文档里能直接「白嫖」的好东西（与已建 8 要素对齐）

MiniYuxi 这轮已经落了企业级 Agent 的骨架（egress / SOC / HITL / cost-breaker / observability）。文档的抽象设计恰好能补进缺口：

| 文档资产 | MiniYuxi 现有对应 | 可直接复用方式 | 等级 |
|---|---|---|---|
| 13 字段审计标准（trace_id / user_id / role / dept_id / action_type / target_resource / risk_level / result / source_system / client_ip …） | `core/soc_audit.py`（SOC 哈希链）+ `core/observability.py`（trace_id / span） | 把 13 字段定为 MiniYuxi 审计日志**标准 schema**，合并进 `soc_audit` | 🟢 低 |
| 4 级风险（low / medium / high / critical）+ 响应策略 | `egress.py` 三态 + `approval.py`（HITL）+ `circuit_breaker.py` | 统一 `risk_level` 枚举；高 / critical 直接接 HITL 与熔断 | 🟢 低 |
| ACP 跨 Agent 权限透传 5 步（SSO→校验→上下文透传→子 Agent 二次校验→脱敏返回） | 暂无 ACP 桥接（新组件） | 直接作为 MiniYuxi 接 Octop 的**接入契约** | 🟢 低 |
| 合规 checklist（TLS1.2+ / AES-256 / 留存≥180 天 / 双写 / 季度复核） | SOC 链已有追加写 + 哈希 | 补「留存期≥180 天」「双写本地 + 远端」「季度复核」三项 | 🟢 低 |
| 全链路 trace_id 串联（用户→Octop→ACP→MiniYuxi→工具→文件） | `observability.py` trace_id | 链路已通，补 Octop↔MiniYuxi 跨系统串联即可 | 🟢 低 |

---

## 4. 给阿长的落地建议（决策点）

1. 🔴 **不按文档的 Docker 多节点落地**。MiniYuxi 保持零 Docker、本地优先；若要做「Octop + MiniYuxi」整合，MiniYuxi 只作为 **ACP Runner 知识插件**对外暴露，走内网，不引入 PG / Milvus / MinIO / 容器隔离。
2. 🟡 **先澄清技术前提再谈集成**。文档把 MiniYuxi 写成 LangGraph + Milvus + PG 是错误的；与 Octop 侧对接前，先发一份「MiniYuxi 实际技术栈清单」（sqlite-vec / FTS5 / 零 Docker / 桌面优先）消除误解，否则对方集成代码会写错。
3. 🟢 **立刻采纳抽象安全设计**：把文档的 13 字段审计 schema + 4 级风险枚举并入 `soc_audit.py` / `observability.py` / `egress.py`，不依赖任何 Docker，是低成本高收益的标准化。
4. 🟡 **5 角色 RBAC + SSO/OIDC 是「未来多租户」叙事**，不是当前必做。只有阿长决定把 MiniYuxi 从「单机桌面 Agent」升级为「多租户 SaaS」时才碰——而那会重新触发「零 Docker」红线的讨论。当前阶段把它当设计储备，不写代码。
5. 🟢 **ACP 桥接层是新组件**，优先级最高的是定义好「身份透传 + 权限校验 + 结果脱敏」的契约（文档 2.3 的 5 步），并且让桥接出口**强制过 `egress.guard()`**，复用已有的出境管控，避免新增一条不受控的数据出境通道。

---

## 5. 与上次 Octop 对比结论的呼应

- 上次审计（`octop-miniyuxi-audit-20260928.md`）结论：Octop 强在 IM 通道 / 专家市场 / ACP 协议领先；MiniYuxi 强在零 Docker / 数据出境合规（egress · SOC · HITL · cost-breaker）/ HR 垂直。
- 本设计文档**印证**了那次结论：Octop 想用 MiniYuxi 补「私有知识库 + 合规」短板，但用 Docker 多租户模板套 MiniYuxi 会水土不服。**正确的整合姿势是 MiniYuxi 以 ACP Runner 插件身份接入 Octop，而不是被改造成 Docker 多节点服务**。

---

*评审人：阿长的助理 · 2026-09-29 · 基准 MiniYuxi 0.4.0 + `requirements.txt` / `core/` 实测*
