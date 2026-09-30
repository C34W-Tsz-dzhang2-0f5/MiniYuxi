# CONTEXT.md — MiniYuxi 共享语言词典（单一真相源）

> 作用：本文件是**全仓术语与边界的唯一真相源**。代码、文档、issue 标题、测试名**必须**使用本词典术语，禁止同一概念长出多个名字（语义扩散）。新术语落地请走 `/domain-modeling`（经 `/grill-with-docs`）。
> 维护：S0 基础设施的一部分（enterprise-agent-scaffolding + vibe-coding-workflow）。改本文件即改契约。

---

## 一、产品定位（最高优先级 · 阿长 2026-09-24 更正，覆盖此前一切表述）

- **MiniYuxi = 企业级 Agent · 零 Docker · 数据可出本机 · 可商用。**
- 「数据可出本机」放开的是**持凭据直连第三方 API**；**不放**「把凭据托管给第三方代持中转」。
- 商用授权红线：**零 copyleft**（GPL/AGPL/SSPL 禁用），引入新依赖前必跑 `scripts/audit_licenses.py`。

## 二、三表面（surfaces）

| 术语 | 含义 | 底座 |
|---|---|---|
| **桌面版** (Desktop) | Tauri 壳 + 本机单进程 | 单用户、单 SQLite 文件；天然**单租户** |
| **网页版** (Web) | `web/` + `run.py`(端口 8801) | 可本机跑，也可对外部署 |
| **共用 core** | `core/` Python | 三端外壳只做传输，业务全在 core |

> ⚠️ 「多租户隔离 / 对外 HA」**仅对"网页版对外部署"形态适用**；桌面版与网页版单租户形态 ➖ 不适用。

## 三、核心模块命名（canonical · 禁止别名）

| 术语（规范名） | 模块 | 一句话职责 |
|---|---|---|
| **sidecar / 副车** | `apps/desktop/src-tauri/binaries/miniyuxi-sidecar.exe` | 冻结的 Python 后端可执行；桌面壳经 `tauri-plugin-shell` 拉起 |
| **egress / 数据出境管控** | `core/egress.py` → `guard()` | 所有出境的**唯一收口点**，三态 allow/deny/approval，进 SOC 链 |
| **approval / 审批卡 / HITL** | `core/approval.py` | 不可逆动作挂起 → 审批卡 → `resume_token` 断点续跑 |
| **multitenant / 多租户闸门** | `core/multitenant.py` | `enforce()` 配额/驻留/MLPS/CMK 闸门 + `readiness` 合规账本 |
| **soc_audit / SOC 审计** | `core/soc_audit.py` | 结构化事件 + **哈希防篡改链** |
| **usage / 成本监控** | `core/usage.py` | 每次 LLM/Embedding 的 token 与成本记录 |
| **provider_router / 供应商路由** | `core/provider_router.py` | 多供应商注册表 + 运行时热切换 + 故障转移 |
| **connectors / 连接器** | `core/connectors.py` | 微信/企微/CRM/ERP/飞书适配器框架 + 健康探测 + 降级 |
| **skills_install / 技能安装** | `core/skills_install.py` | 粘贴/路径/URL 三来源安装卸载（只作提示词注入，不执行代码） |
| **skills_catalog / 技能目录** | `core/skills_catalog.py` | 技能**唯一加载器** + `invalidate_cache()` 单点刷新 |
| **mcp_ruoyi_adapter** | `tools/mcp_ruoyi_adapter.py` | RuoYi 业务集成适配器（B1–B4） |
| **eval_harness / 评测 harness** | `core/eval_harness.py` | YAML 任务 + Pass@1/k + LLM-as-Judge |
| **agent_runtime / 运行时** | `core/agent_runtime.py` | 进程级 Agent 运行时管理 |
| **agent_loop / 智能体循环** | `core/agent_loop.py` | ReAct 反思循环内核（`run()`）；一切工具执行的唯一入口 |
| **event_stream / 事件流** | `core/agent_loop.py` emit → SSE | Agent 循环标准事件（`lifecycle`/`tool`/`assistant`）流式推送前端 |
| **lane / 会话通道** | `core/agent_runtime.py` | **同会话串行**（`status=="running"` 拒并发）· 跨会话并行；子 Agent 用独立 lane |
| **swarm / 子 Agent 集群** | `core/subagent.py` | 主 Agent 拆子任务 → 隔离子会话并行 → Fan-in 汇总（`maxSpawnDepth=1`） |
| **heartbeat / 心跳** | （规划中） | 无用户消息时定时自主复盘/自检/推进 |

## 四、企业级八要素术语（enterprise-agent-scaffolding）

1. **多租户隔离** (Tenant Isolation)
2. **身份与权限 / 最小权限** (IAM / Least Privilege)
3. **审计日志** (Audit Logging) — 落地为 **SOC 哈希链**
4. **可观测性 / Tracing** (Observability) — 落地为 `core/observability.py`（`start_trace`/`span`/`get_metrics`），2026-09-29 达标
5. **成本控制 / 熔断** (Cost Governance / Circuit Breaker) — 落地为 `core/circuit_breaker.py`（`BudgetGuard`），2026-09-29 达标
6. **人工审批 / HITL** (Human-in-the-loop)
7. **行为评测集** (Eval Suite)
8. **CI/CD 与灰度** (Deployment)

## 五、约定与禁忌（naming conventions）

- **禁止语义扩散**：同一概念一个名字。例：出境管控只叫 `egress`（不叫 export/outbound/data-leave）；审批只叫 `approval`/`HITL`（不叫 review/check）。
- **出境单一收口**：任何数据出本机必须过 `egress.guard()`，新增出口必过闸，否则出境清单不成立。
- **不可逆动作独立人审**：发消息/删数据/转账等走 `approval` 卡，**禁止模型自审自己是否安全**。
- **桌面版默认单租户**；写「多租户隔离」相关代码前先确认是针对网页版对外部署形态。
- **契约先行**：技能字段契约看 `skills/SKILL_CONTRACT.md`；版本号唯一来源 `core/version.py`。
- **事件流单一来源**：前端一切「思考/工具调用」展示**只**读 `event_stream`（`lifecycle`/`tool`/`assistant` 三型），禁止前端自己拼装过程态。
- **工具执行唯一入口**：所有工具调用必须经 `agent_loop.run()` → `tools_registry.run_tool_governed()`（过 egress/HITL/熔断/审计），**禁止**旁路直调。

## 六、外部概念（引用时保持原名）

- **RuoYi**：生产级业务系统（OA/CRM/ERP/HRM），经 `mcp_ruoyi_adapter` 对接。
- **MCP**：Model Context Protocol，连接器扩展协议。
- **Tauri / WiX**：桌面壳框架 / MSI 打包工具（v3.14 便携版）。
