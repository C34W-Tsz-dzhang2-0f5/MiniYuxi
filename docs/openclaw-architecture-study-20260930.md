# OpenClaw Agent 架构技术学习 · 对标 Octop / WorkBuddy · MiniYuxi 落地路线

> 来源：7 篇豆包技术对话（2026-09-30），围绕 OpenClaw（WorkBuddy / Octop 的开源 Agent 引擎底座）的调度、任务拆解、反思循环
> 目的：为 MiniYuxi 对标 Octop / WorkBuddy 底层做技术学习；**目标 = MiniYuxi 网页版 + 桌面版完整可运行**
> 阅读原则（阿长指定）：宏观架构 → 核心概念 Agent Loop → 运行时源码导读 → 高级机制 → 运维与安全
> 原文落盘：`.scratch/oc-research/oc1.md ~ oc7.md`

---

## 0. 一句话结论

OpenClaw 是 WorkBuddy / Octop 的**开源 Agent 引擎底座**（MIT），内核就是一个 **LLM 驱动的 ReAct 反思循环**——「任务拆解 → 调工具 → 结果回灌 → 反思 → 再规划 → 循环到无工具调用为止」；外层靠 **Gateway 网关 + Embedded Runner + Lane 队列 + Swarm 子 Agent + 沙箱 + 审计账本** 撑起企业级并发与安全。

**对 MiniYuxi 的结论**：我们已自研出**同构**的 `core/agent_loop.py`（ReAct + 熔断 + 观测），架构方向正确、不落后。真正缺的是四块「企业级运行时」能力——**① 子 Agent Swarm 并行、② 会话 Lane 串行、③ 事件流 SSE、④ 心跳自主循环**；以及**把主对话真正接到这套运行时上**（本会话已修 `wb_workbench.chat` → `agent_loop`）。

---

## 1. 宏观架构（OpenClaw / WorkBuddy 分层）

| 层 | 组件 | 职责 | MiniYuxi 对位 |
|---|---|---|---|
| 接入层 | Channels（IM/Web/桌面/Cron/API） | 多渠道消息接入 | 🟡 有 web/桌面；IM 通道缺（仅 RuoYi MCP） |
| 网关层 | **Gateway** | 统一入口、渠道适配、消息路由、会话管理、事件分发、审计日志，长驻进程 | 🟡 `api.py` 承担一部分，无独立网关/事件总线 |
| 运行时 | **Embedded Agent Runner** | 会话隔离、Lane 队列、超时熔断；把内核事件转成标准 `lifecycle/tool/assistant` 事件流 | 🔴 无（`agent_loop.run` 是同步函数，无会话队列/事件流） |
| 内核 | **@openclaw/agent-core** | `runAgentLoop`：ReAct 反思循环、LLM 调用、工具执行、记忆、SOUL 人格 | 🟢 **已有** `core/agent_loop.py`（同构） |
| 能力层 | 专家(SOUL) / 技能(SKILL) / 连接器(MCP) / 资料库(RAG) / 工作空间(沙箱) | Agent 可用的角色与工具 | 🟢 四件套齐全（`experts.py`/`skills_catalog`/`mcp_client`/`rag.py`/`security.py`） |
| 编排 | **Swarm** 子 Agent 集群 | 主 Agent 拆解任务 → 派生隔离子会话并行执行 → Fan-in 汇总 | 🔴 无并行派生（`subagent.py` 有雏形但未接循环） |
| 存储 | SQL / 向量库 / 对象存储 | 会话、元数据、RAG、文件 | 🟢 SQLite + sqlite-vec（零 Docker，见下） |

> **WorkBuddy ≠ 开源**：WorkBuddy 桌面端 = OpenClaw 内核 + **闭源** Electron 客户端 + 本地文件沙箱 + 腾讯云鉴权 + 专家团编排 + IM 远程触发。能拿到的代码只有：① OpenClaw 开源底座（`@openclaw/agent-core`，MIT）；② 官方 SDK Demo（`cnb.cool/codebuddy/agent-sdk-demos`）。**沙箱、鉴权、编排是腾讯自研闭源部分。**

---

## 2. 核心概念：Agent Loop（任务拆解 + 反思循环）【最关键】

OpenClaw 官方架构文档原版伪代码（内核等价物）：

```typescript
async function agenticLoop(trigger: AgentTrigger) {
  // 1. 加载人格 SOUL.md、心跳规则 HEARTBEAT.md、召回历史记忆
  const soul      = await loadFile('SOUL.md');       // 角色定义、任务拆解规则
  const heartbeat = await loadFile('HEARTBEAT.md');  // 自主反思 / 自检规则
  const memory    = await retrieveMemory(trigger, 20);

  // 2. 第一轮 LLM 推理：任务拆解，规划执行步骤
  let llmResponse = await callLLM({ system: `${soul}\n${heartbeat}`,
                                    messages: [...memory, trigger.userMessage] });

  // 3. 工具调用反思循环：核心！
  while (llmResponse.hasToolCall()) {
    const toolResult = await executeTool(llmResponse.toolCall);
    // 【反思环节】工具结果回灌上下文，LLM 重新思考、评估、规划下一步
    llmResponse = await callLLM({ system: `${soul}\n${heartbeat}`,
      messages: [...memory, trigger.userMessage, llmResponse.assistantMessage,
                 { role: "tool", content: JSON.stringify(toolResult) }] });
  }

  // 4. 循环终止：无工具调用 → 输出最终答案；持久化记忆 + 上下文压缩
  await saveToMemory(trigger, llmResponse);
  await compactIfNeeded(trigger.sessionId);
  return llmResponse.finalText;
}
```

**三句话吃透**：
- **任务拆解** = 首次 LLM 调用（读 SOUL.md），把大目标拆成子步骤；
- **反思循环** = `while`：工具结果回传 → 模型自问「达标了吗？要继续调工具吗？要改计划吗？」；
- **终止条件** = 模型输出自然语言、不再返回 `tool_call`（或达 `maxTurns` / 超时强退）。

> **MiniYuxi 对位**：`core/agent_loop.py::run()` 已是同构实现（`MAX_LOOPS=6`、`tool_choice=auto`、tool_calls 解析回填、熔断 `BudgetGuard`、`observability.span`）。**内核层面不缺，缺的是外层运行时与事件流。**

---

## 3. 运行时源码导读

### 3.1 会话入口：`src/agents/embedded-agent-runner/run.ts`
```typescript
export async function runEmbeddedPiAgent(input, emit) {
  const { sessionId, workspace, maxTurns = 10, soul, memory, tools } = input;
  emit({ type: "lifecycle", phase: "start", sessionId });
  const result = await runAgentLoop({
    messages: input.initialMessages, soulPrompt: soul, memory, tools, workspace,
    maxIteration: maxTurns,
    onStep: (step) => emit({ type: "tool", payload: step.toolCall }),  // 流式推事件
  });
  emit({ type: "lifecycle", phase: "end", payload: { final: result.content } });
  return result;
}
```
要点：**会话队列 + 流式事件 + 最大迭代保护**（`maxTurns=10`）。

### 3.2 子任务拆分：Swarm spawn
```typescript
async function spawnSubAgents(taskPlan, parentSessionId) {
  const childSessions = [];
  for (const subtask of taskPlan.subTasks) {
    const childSession = await sessionManager.spawnIsolatedSession({
      parentSessionId, task: subtask, workspace: parentSession.workspace });
    childSessions.push(childSession);
  }
  const results = await Promise.all(childSessions.map(s => s.waitResult()));
  return aggregateResults(results);   // Fan-in 汇总
}
```

---

## 4. 高级机制（企业级运行时四件套）

| 机制 | OpenClaw 做法 | 价值 | MiniYuxi |
|---|---|---|---|
| **Swarm 子 Agent** | 主 Agent 拆子任务 → `spawnIsolatedSession` 独立 session+workspace → `Promise.all` 并行 → Fan-in 汇总 | 多专家 / 大任务并行 | 🔴 缺 |
| **Lane 队列** | session lane（**同会话串行**，防状态/文件竞争）；subagent lane（默认并发 8）；全局 main lane | 并发安全 + 限流 | 🔴 缺 |
| **Heartbeat 心跳** | 无用户消息也定时主动复盘 / 自检 / 推进（`HEARTBEAT.md`） | 自主反思 | 🟡 `scheduler.py` 有定时，但非"自检" |
| **Memory + compaction** | 共享向量记忆；会话结束自动压缩上下文控 token | 长任务不爆上下文 | 🟡 有 `memory.py`/`memory_slim.py`，无自动 compaction |
| **Session 快照** | 会话隔离、快照、断点续跑、队列 | 中断可恢复 | 🟡 `taskflow.py` 部分 |

**关键约束（照抄进 MiniYuxi 设计）**：
- `maxSpawnDepth = 1`：子 Agent 默认**不能再派生孙 Agent**，防 Agent 风暴；
- **权限冒泡**：子 Agent 遇高危操作**不直接执行**，暂停向上申请审批（对应 MiniYuxi 的 HITL）；
- **子 Agent 超时熔断**：单个失败不阻塞其余；Fan-in 收集全部（含失败），主 Agent 决定重试或标注。

---

## 5. 运维与安全

| 维度 | OpenClaw | MiniYuxi 对位 |
|---|---|---|
| 统一入口 | Gateway 长驻进程，审计埋点 | 🟡 `api.py` |
| 工作空间沙箱 | 容器隔离 / 目录白名单；`允许完全访问` 开关映射到 PolicyEngine | 🟢 `core/security.py`（敏感路径黑名单）+ 工作空间概念 |
| 权限模型 | RBAC + SSO/OIDC + 部门隔离 | 🟡 `auth.py`/`multitenant.py` 雏形 |
| 审计账本 | lifecycle/tool/assistant 全事件入账本，可追溯 | 🟢 `core/soc_audit.py`（SOC 哈希链）+ `observability.py` |
| 成本治理 | 全局最大迭代、限流 | 🟢 `core/circuit_breaker.py`（本会话新增，**OpenClaw 文档未强调，是 MiniYuxi 的加分项**） |
| 数据出境 | —（腾讯云侧） | 🟢 `core/egress.py`（**MiniYuxi 独有护城河**） |

---

## 6. 对标总表：OpenClaw / Octop / WorkBuddy / MiniYuxi

| 能力 | OpenClaw（开源底座） | Octop（腾讯云开源） | WorkBuddy（闭源商用） | **MiniYuxi** |
|---|---|---|---|---|
| 内核 ReAct 循环 | ✅ runAgentLoop | ✅ harness-agent（自研） | ✅ 同源 | ✅ `agent_loop.py` |
| SOUL 人格 | ✅ SOUL.md | ✅ 专家库/MBTI | ✅ 专家团 | ✅ `experts.py` |
| 技能 | ✅ SKILL.md | ✅ 技能市场 | ✅ | ✅ `skills_catalog` |
| MCP 连接器 | ✅ | ✅ | ✅ | ✅ `mcp_client` |
| Swarm 子 Agent 并行 | ✅ | ✅ | ✅ 专家团编排 | 🔴 **缺** |
| Lane 会话队列 | ✅ | ✅ | ✅ | 🔴 **缺** |
| 事件流（SSE） | ✅ lifecycle/tool/assistant | ✅ | ✅ | 🔴 **缺**（前端无流式） |
| Heartbeat 自主循环 | ✅ | ✅ | ✅ | 🟡 部分 |
| 沙箱 | ✅ | ✅ | ✅（闭源） | 🟡 `security.py`，非容器 |
| IM 通道 | ✅（多 IM） | ✅（飞书/企微等） | ✅（企微/微信） | 🔴 缺 |
| 多租户 RBAC | ✅ | ✅ | ✅ | 🟡 雏形 |
| **零 Docker** | ❌（可自托管但重） | ❌ | ❌ | ✅ **独有** |
| **数据出境管控** | ❌ | ❌ | ❌ | ✅ **独有（egress）** |
| **成本硬熔断** | 🟡 仅最大迭代 | 🟡 | 🟡 | ✅ **独有（BudgetGuard）** |
| **可商用授权** | ✅ MIT | ✅ | ❌ 闭源 | ✅ MIT |
| 前端 | — | React+TS+Vite+AntD | Electron | 🟡 原生 JS（`wb_workbench.js`） |

**结论**：MiniYuxi 在「**轻量 / 合规 / 成本治理**」三条线上**领先**（零 Docker、egress、BudgetGuard、MIT）；在「**企业级运行时**」上**落后**（Swarm、Lane、事件流、IM 通道）。**补运行时，守合规线**，就是 MiniYuxi 的对标打法。

---

## 7. MiniYuxi「网页版 + 桌面版完整可运行」差距清单 + 落地路线

### 7.1 必须先修的阻断项（🔴 否则谈不上"可运行"）

| # | 问题 | 状态 |
|---|---|---|
| 1 | **主对话不执行工具**（`wb_workbench.chat` 只做单次 LLM） | ✅ **本会话已修**（commit `9decfdb`）：agent 模式走 `agent_loop` |
| 2 | 工具清单未注入提示词 → 模型只讲解不执行 | ✅ 已修（`tool_inventory_text` + 强制指令） |
| 3 | 无「写代码 / 文件」工具 → 写代码做不到 | 🔴 **待定范围**（需 HITL + 路径白名单，安全敏感） |
| 4 | 无事件流 → 前端看不到思考/工具调用过程 | 🔴 待做（SSE） |
| 5 | 桌面装机版需重出 MSI 才含新修复 | 🔴 待做 |

### 7.2 对标路线（按性价比排序）

| 优先级 | 动作 | 收益 | 成本 |
|---|---|---|---|
| P0 | 修完阻断项（工具链路✅ / 写代码工具 / SSE / 重出 MSI） | 从"不能用"到"能用" | 中 |
| P1 | **事件流 SSE**：`agent_loop` 每步 emit `lifecycle/tool/assistant`，前端流式渲染 | 体验质变（看得到思考） | 中 |
| P2 | **Lane 会话队列**：同会话串行，防并发冲突 | 稳定性 | 低 |
| P3 | **Swarm 子 Agent**：主 Agent 拆子任务并行（`maxSpawnDepth=1`） | 大任务能力 | 高 |
| P4 | **Heartbeat 心跳**：定时自主复盘 | 自主性 | 中 |
| P5 | 前端工作台升级（见 §8） | 观感/易用 | 高 |

---

## 8. 前端工作台规格（来自 oc5 / oc6 / oc7）

### 8.1 界面结构（与 MiniYuxi 现有 UI 高度一致）
- **顶部场景 Tab**：日常办公 / 代码开发 / 设计创意 —— 切换 = 换一套「SOUL 角色 + 技能集 + 预置提示词」（不是页面跳转）；
- **技能快捷卡片**：横向滚动，点击填入 `/技能名`；
- **输入框**：`@` 引用文件/资料（RAG）、`/` 唤起技能、`+` 菜单（文件/专家/技能/连接器）；
- **底部**：工作空间选择 + **允许完全访问**开关（映射沙箱 PolicyEngine：开=可读写工作空间；关=仅手动上传文件，禁遍历目录）；
- **左侧菜单**：新建任务 / 助理 / 项目 / 专家·技能·连接器 / 定时任务 / 资料库 / 更多。

> MiniYuxi 现有 `web/wb_workbench.js` 已具备上述**大部分**（本会话刚清理过顶部导航）。差距在**流式事件渲染**与**场景化技能卡**。

### 8.2 前端骨架选项（oc7 给了完整 React 骨架）
`React18 + TS + Vite5 + AntD5`，对接 `POST /api/scene/load` + `POST /api/agent/run`（SSE）。

**⚠️ 决策点**：是否要把 MiniYuxi 前端从**原生 JS** 迁到 **React 骨架**？
- 迁移收益：组件化、生态、观感；
- 迁移成本：高（现有 `wb_workbench.js` 数千行 + 桌面 Tauri 复用 `web/`）；
- **建议**：**不迁移**，只在现有前端补「SSE 事件流 + 场景技能卡」；React 骨架留作**独立演示/对外样板**。

---

## 附录：7 篇原文与要点索引

| 文件 | 标题 | 要点 |
|---|---|---|
| oc1.md | OpenClaw Agent 调度源码与文档阅读顺序整理 | WorkBuddy/OpenClaw 关系、五阶段阅读顺序、Agentic Loop 伪代码、runner 入口、Swarm |
| oc2.md | OpenClaw Agent Loop 最小 TS Demo 与时序图 | Mermaid 时序图 + 最小可运行 runAgentLoop Demo |
| oc3.md | OpenClaw 架构与 TS Demo 实现 | Gateway/Runner/agent-core 三层 + 事件流 + Swarm 增强 Demo |
| oc4.md | Swarm 子 Agent 并行任务拆解时序图 | Lane 队列、spawn 隔离、权限冒泡、事件流、共享记忆、容错 |
| oc5.md | 截图界面实现方案 | 工作台 UI 规格（场景 Tab/技能卡/输入框/侧边栏/工作空间权限）+ 四大模块 |
| oc6.md | 工作台相关配置与代码 | React 组件伪代码 + scene.yaml / SOUL.md / SKILL.md 配置样例 |
| oc7.md | Agent 工作台前端项目骨架 | React+TS+Vite+AntD 完整可运行骨架（`/api/scene/load` + `/api/agent/run` SSE） |

---

*整理：阿长的助理 · 2026-09-30 · 基于 7 篇豆包技术对话（AI 生成，原理部分已按 MiniYuxi 实际代码核验）*
