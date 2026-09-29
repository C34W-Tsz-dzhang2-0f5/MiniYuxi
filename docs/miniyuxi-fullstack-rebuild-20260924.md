# MiniYuxi 基础设施"全栈化"改造规划（基于 2026-09-23 GitHub 热榜文章）

> 来源：`mp.weixin.qq.com/s/7ednZoymirsAiqSVW2teEw`（猫猫小屋 · GitHub 热门开源项目日报 2026.09.23）
> 对象：阿长点名的 7 个方向 —— ax(编排) / substrate(沙箱) / treg(工具市场) / univer(办公操作面) / BrowserSkill=jev-ultrafast(真实浏览器) / kev(决策模型) / Jev 生态=jev-chat-jarvis(手机副驾)
> 性质：**研究 + 选型 + 落地**。第一波 univer（P0）与第二波本地工具市场（P1）**已落地并装机**。
> **2026-09-24 更新**：按阿长更正的定位（企业级 Agent / 数据可以出本机 / 零 Docker / 可商用）**重推全文决策**，并新增商用授权审计。

---

## 一句话结论

文章描述的"全栈化"是**云端/K8s 原生**的 Agent 基础设施（ax+substrate 都依赖 Kubernetes）。MiniYuxi 的定位是**企业级 Agent：数据可以出本机、零 Docker、可商用、Windows-Tauri**——与"云原生全栈"在**底座（零 Docker）**上仍然冲突，但**不再与"数据出境"冲突**。

> ⚠️ **本节已于 2026-09-24 按阿长更正重推。** 初版把"数据不出本机"当作硬约束，据此否掉了 treg 与手机副驾——**前提错了**。更正后的正确姿势是：

**"数据可以出本机"只解除了一条约束轴，不是全部。** 真正需要分别把关的是三条**互不替代**的轴：

| 轴 | 约束 | 被它否掉的东西 |
|---|---|---|
| **① 底座** | 零 Docker | ax（要 K8s）、substrate（gVisor/microVM+K8s） |
| **② 授权** | 可商用 | 任何非宽松 license 的组件/模型权重 |
| **③ 第三方权益** | 不得未经同意采集第三方个人信息 | jev 手机副驾（Android 无障碍读私聊——采集的是**对话对方**的信息，与"我方数据能不能出本机"无关） |

因此正确姿势是：**吸收每层理念；能云端就云端、该本地就本地（不再一刀切要求本地）；对"依赖 Docker/K8s"的组件不搬，对"读私聊"的组件不抄，对商用授权逐项核验。**

| 层 | 文章组件 | 对 MiniYuxi 价值 | 适配性 | 决策（2026-09-24 更正后） |
|---|---|---|---|---|
| 编排 | **ax**（Google，K8s 声明式编排） | 声明式 YAML 编排 + 四原语 + 检查点 | 🟡 重、需 K8s | **P2 · 抄理念不搬组件**（**零 Docker 否掉运行 ax 本体**；Gateway 出站白名单思想并入工具治理） |
| 沙箱/执行 | **substrate**（gVisor/microVM + K8s，百万沙箱） | 高密度隔离不可信代码 | 🔴 需 K8s+microVM | **不抄**。理由已从"合规"**收窄为"零 Docker 硬冲突"**（gVisor/microVM 比 Docker 更重）；且 MiniYuxi 不执行用户任意代码 |
| 工具市场 | **treg**（OpenRouter 式，3000+ 工具，凭据服务端注入） | 统一工具接入、按次计费 | 🟡 理念好 | **P1 · 仍走"本地工具市场"**（**已落地**）。⚠️ 见下方"treg 再评估"——"数据可出本机"**不等于**"可以把凭据托管给第三方" |
| 办公操作面 | **univer**（开源 Office SDK，TS 全栈，Canvas+公式引擎+MCP） | 让 Agent 真实操作表格/文档/幻灯片 | 🟢 高（HR 刚需） | **P0 · 已落地并装机**。授权已审计：**Apache-2.0，可商用 ✅** |
| 真实浏览器 | **jev-ultrafast / BrowserSkill**（超快浏览器智能体） | Agent 真实操作网页（查公开政策/招聘） | 🟢 **上调**（数据可出→云端可用） | **P2 · 升级为"可选云端"**：本地 Playwright 仍优先（快、无数据外流），云端作为补充；企业级需审计其数据流向与 ToS |
| 决策模型 | **kev**（0.8B/4B/9B 判断模型，20 分钟微调） | 轻量"合规判断专家"，替代部分 LLM 判断 | 🟢 **上调**（数据可出→可云端微调） | **P1 · 试点**。微调数据可出本机，路径更顺；⚠️ 但**模型权重/底座的商用授权须先核** |
| 手机副驾 | **jev-chat-jarvis**（Android 无障碍读聊天候选回复） | 手机端 Agent 副驾 | 🔴 Android 专用、读私聊 | **不抄**。理由已**收窄为"第三方权益"**（读私聊采集对话对方信息），**不再援引"数据出境"** |

### ⚠️ treg 再评估（"数据可以出本机"下的重新判断）

初版用"数据出境"一刀切否掉 treg。更正后要**拆成两件事**，结论仍然是不接 treg 服务，但理由换了：

| 拆解 | 内容 | 新定位下 |
|---|---|---|
| **(a) 我自己持有凭据，直连第三方 API** | MiniYuxi 用自己申请的 key 调 OpenAI/豆包/企查查等 | ✅ **完全放开**——"数据可以出本机"直接覆盖 |
| **(b) 把凭据交给 treg，由 treg 代持并中转** | 一个 treg token 调 3000+ 工具，凭据留 treg 服务端 | ❌ **仍不做**。理由不是"数据出境"，而是：① **凭据代持**引入一个与业务无关的第三方信任根，企业级安全上不划算；② **按次计费**= 工具调用成本不可控、不可审计；③ **授权/条款**须核（商用可用性、SLA、数据处理协议）；④ 出问题时**责任链断裂**（我的 HR 数据经它中转，谁负责说不清） |

> 一句话：**"数据可以出本机"放开的是 (a) 这条直连路径；没有放开 (b) 的凭据代持。** 本地工具市场（P1）已按 (a) 落地——工具元数据与凭据全在本机，需要外呼时由 MiniYuxi 自己直连。

### 「企业级 Agent」这个定位额外要求什么（新增）

既然定位升级为**企业级**，下面这些不能只停留在"能跑"：

| 要求 | MiniYuxi 现状 | 差距 |
|---|---|---|
| 多租户隔离 | ✅ `tenant_id` 贯穿各表 | 已具备 |
| 权限控制 | ✅ `need(perm)` 依赖注入 | 已具备 |
| 审计留痕 | ✅ `db.audit` + 哈希链 | 已具备 |
| **商用授权干净** | ✅ **本轮已审计**：office 依赖 132 包全为 MIT/Apache-2.0/BSD/ISC，**无 copyleft、无上报埋点** | 已具备 |
| **数据出境可配置** | ✅ **0.4.0 已落地**：`core/egress.py` —— 出境闸门（5 类目的地 × 10 个出口全过闸）+ 三态模式（allow/deny/approval）+ 按数据分级配置 + 出境日志（含被拒的，入 SOC 哈希链）+ 三档姿态预设 | ✅ 已具备 |
| **版本一致性** | ✅ **0.3.0 已修**：唯一来源 `core/version.py`，6 处清单由 `scripts/check_version_consistency.py` 强制校验（可进 CI） | ✅ 已具备 |
| 第三方依赖授权台账 | ✅ **已做成可复跑脚本** `scripts/audit_licenses.py`（`--pkg` / `--bundle`），纳入引入新依赖时的检查 | ✅ 已具备 |

> 商务/法务提示（非技术阻断）：即便数据可以出本机，面向企业客户交付时，**个保法下的告知同意与数据处理协议(DPA)** 仍是部署侧必备动作。技术层已把"出境开关 + 出境日志"产品化（见上表），合规动作有了技术落点。
>
> 出境管控的两条设计取舍，交付时需向客户说明：
> ① **默认全放行** —— 定位是"数据可以出本机"，开箱即禁会让产品不可用；企业侧用预设一键收紧。
> ② **guard 异常默认 fail-open** —— 不让审计组件变成单点故障；严格场景设 `MINIYUXI_EGRESS_FAIL_MODE=closed`。

---

## 文章组件还原（先对齐事实）

| 名 | GitHub | 是什么 | 关键事实 |
|---|---|---|---|
| kev | jaredpalmer/kev | 小型"决策模型"家族 | Qwen3.5 底座+LoRA+指针头，0.8B/4B/9B；一次前向答 是/否/多选/评分+校准概率；兼容 TypeSafe System One API；0.8B 单卡微调 20 分钟；可自有数据定制 |
| ax | google/ax | 声明式智能体编排运行时 | K8s 上跑自主 Agent；kubectl 式 CLI + YAML 清单；四原语 **Task**(沙箱隔离跑不可信代码)/**Workspace**(预置 Git+MCP)/**Gateway**(出站流量白名单)/**Model**(统一配 LLM)；`ax ssh` 调试、`ax suspend/resume` 检查点；**早期、接口可能变** |
| substrate | agent-substrate/substrate | 高密度安全沙箱运行时 | gVisor/microVM + K8s 控制平面；百万级沙箱、10x 资源密度、<500ms 恢复；是 ax 的底层执行基座；**早期勿上生产** |
| treg | superdesigndev/treg | 代理工具版 OpenRouter | 一个 base URL + 一个 token 调 3000+ 工具端点(60+ 提供商)；按次计费、免注册各家账号；**凭据留在服务端注入**；支持 Claude Code 插件 + MCP |
| univer | dream-num/univer | 开源办公 SDK（AI Agent 办公操作面） | 同一运行时构建 表格/文档/幻灯片/关系数据表；Canvas 渲染 + 完整公式引擎 + 插件架构；结构化 API 编辑、截图验证、隔离 Worktree(代理草稿+人工审查后合并)；配套 MCP；TS 全栈 |
| jev-ultrafast (BrowserSkill) | browser-use/jev-ultrafast | 超快浏览器智能体 | 单次往返决策，7 秒完成航班搜索，协议调用降 90%；Browser Use 官方 |
| jev-chat-jarvis (Jev 生态) | jev-chat/jev-chat-jarvis | 手机对话副驾 | Android 无障碍读聊天界面；AI 分析意图+危险等级，生成 3 条排序候选回复**绝不自动发送**；支持 QQ/X 私信，飞书 OCR 兜底，微信新版已停支持；内容只发往自配模型、知识库/历史本机、无自建服务器 |

---

## 逐层落地路径（与 MiniYuxi 现有体系衔接）

### ✅ P0/P1 · univer（办公操作面）—— 优先级最高，HR 最直接对口
- **现状缺口**：MiniYuxi HRM 已有 49 张结构化表单（`core/hrm_schema.json`），但"生成/编辑 Office"能力为零——HR 高频刚需（Offer 文档、薪酬表、离职证明、制度 Word、汇报 PPT）目前只能产出纯文本。
- **怎么抄**：univer 是纯本地 TS SDK，嵌进 `web/` 前端即可；或用其官方 MCP 让 Python 内核 Agent 调。
- **衔接**：上游接已有"知识库检索 / 制度地图"，下游产出可编辑 Office（而非截图式文本）。对应 ZCode 已落地的"知识库可点击引用"可直接喂给 univer 生成合规文档。
- **成本**：中（TS SDK 体积大，需评估 Tauri 前端集成；MCP 路径较轻）。
- **风险**：🟢 低。**纯本地运行、零外呼**——在"数据可以出本机"的新定位下，这不是"必须"而是**加分项**（HR 表格/合同天然敏感，能不出本机更好）。

### ✅ P1 · treg 理念 → 本地工具市场（**已落地并装机**）
- **现状基础**：MiniYuxi 已有 `skills/` 技能目录 + 工具注册表（`core/tools_registry`）+ 工具治理。
- **怎么抄**：把"统一接入 + 工具目录"理念本地化——做**本机工具市场**（工具元数据集中在 `skills/` 与 `tools_registry`，**凭据留本机 keyring，不送任何第三方服务端**）。已实现：分类/标签/风险/来源元数据 + 启停开关 + 审计留痕。
- **不接 treg 服务的理由（2026-09-24 更正）**：~~HR 数据经此外转=出本机，踩个保法~~ ← **此理由已失效**（定位明确数据可以出本机）。
  正确理由见上方"treg 再评估"：**凭据代持引入无关信任根 + 按次计费不可控不可审计 + 责任链断裂**。注意区分
  **(a) 自己持凭据直连第三方 API**（✅ 放开）与 **(b) 把凭据托管给 treg 代持中转**（❌ 仍不做）。
- **价值**：用统一工具目录收敛 MiniYuxi 现有工具调用入口，降低新工具接入成本；启停可控、行为可审计。

### ✅ P1 · kev（决策模型）→ 安全分层判断器
- **现状基础**：MiniYuxi 已有 Hermes 安全分层（B-5）+ 工具治理 + 审计哈希链，大量"该放行/拒绝/合规与否"的判断目前靠 LLM+规则，延迟与成本偏高。
- **怎么抄**：用 kev 思路训一个**"合规判断专家"小模型**（0.8B，单卡 20 分钟微调，用 HR 合规数据），替代部分 LLM 判断调用，降延迟/成本、可控可定制。
- **2026-09-24 更正**：初版把它定位成"**本地**小模型"。更正后**微调数据可以出本机**（可走云端微调），路径更顺；是否**必须本地推理**取决于企业客户的部署要求，两者都可支持。
- **⚠️ 前置**：落地前必须核 **kev 底座模型权重的商用授权**（Qwen3.5 系列各尺寸授权条款不同，"可商用"是本项目硬约束）+ kev 自身 license。

### 🟡 P2 · ax 理念 → 声明式编排 + Gateway 白名单（不搬 ax）
- **现状基础**：MiniYuxi 已有 agent loop + 子智能体（generator/critic）+ 调度。
- **怎么抄**：吸收 ax 的"声明式编排 + **Gateway 出站流量白名单**"思想——把 MiniYuxi 已有的出站管控（Hermes B-5 安全分层）显式做成"出站白名单"机制。**注意**：数据可以出本机后，"出站白名单"的价值从"合规阻断"变为"**成本/风险管控 + 可审计**"，仍值得做。
- **不搬**：ax 本体需 K8s → 与**零 Docker** 硬冲突（这是现在唯一的、也是决定性的理由）；且早期接口会变。

### 🟢 P2 · jev-ultrafast 能力 → 浏览器自动化（本地优先，云端可选）
- **怎么抄**：用本机已装的 **Playwright**（验收已用）实现"真实浏览器"能力，限定**只读公开信息检索**（查公开政策、招聘公开页），绑定现有 `MINIYUXI_APPROVE_WEB_SEARCH` HITL 闸门。
- **2026-09-24 更正**：初版写"**绝不接** jev 云端服务"。更正后**云端浏览器智能体不再是红线**（数据可出本机）→ 决策从"绝不做"上调为"**可选补充**"：本地 Playwright 优先（更快、更省、数据不外流），云端作为能力兜底。
- **仍需把关**：公网自动化的 **ToS/robots 合规**与**抓取对象是否为个人信息**——这条与"数据能不能出本机"无关，是独立约束。

### ❌ 不抄 · substrate（沙箱）
- **理由（2026-09-24 收窄）**：初版理由是"合规+本地优先"。更正后**唯一决定性的理由是「零 Docker」硬冲突**——gVisor/microVM + K8s 控制平面比 Docker 更重，Windows 单机不可能落地。
- 另：MiniYuxi 不执行用户任意代码（工具调用走受控工具集），不存在"百万级不可信代码沙箱"需求；**工具治理+审计已覆盖本地安全分层**。

### ❌ 不抄 · jev-chat-jarvis（手机副驾）
- **理由（2026-09-24 收窄，与"数据出境"脱钩）**：它靠 Android 无障碍服务**读取用户私聊内容**——采集的是**对话对方**（第三方）的个人信息，**这是第三方权益问题，不是我方数据能不能出本机的问题**。即便定位改成"数据可以出本机"，也**不构成**采集第三方信息的正当性。
- 另：Android 专用、平台适配脆弱（微信新版已停支持），与 MiniYuxi 桌面端定位不直接相关。**明确不抄**。

---

## ⚠️ 三条把关轴（2026-09-24 按新定位重写）

> 初版这里写的是"数据不出本机/不出境"当第 1 条红线——**前提已更正，作废**。以下是替代版本。

| # | 轴 | 具体把关 |
|---|---|---|
| 1 | **底座：零 Docker** | 不引入任何依赖 Docker/K8s/容器运行时的组件（ax/substrate 本体）。这条**不受"数据可出本机"影响**，是硬约束。 |
| 2 | **授权：可商用** | 每个新引入的依赖、SDK、模型权重，逐项核 license。**禁 copyleft（GPL/AGPL/SSPL）**；确认无强制回馈条款、无商用限制。✅ office 链路已审计（132 包全宽松）。 |
| 3 | **第三方权益** | 不得未经同意采集第三方（对话对方、被爬站点用户）的个人信息；公网自动化须守 ToS/robots。**与"我方数据能否出本机"无关**。 |

**已放开（不再是红线）**：数据出本机、调用云端 LLM/API、云端微调、云端浏览器智能体——**前提是企业侧有出境开关与出境日志可审计**。

> ✅ **该前提已于 0.4.0 落地**：`core/egress.py` —— 5 类目的地 × 10 个出口全部过闸，
> 支持按数据分级配置（allow/deny/approval）+ 出境日志（含被拒的，写入 SOC 哈希链）。
> 详见 CHANGELOG `[0.4.0]`。
**仍然要做（工程要求，非红线）**：出站白名单/HITL 审批门（`MINIYUXI_APPROVE_WEB_SEARCH` 已有）——理由从"合规阻断"转为"成本与风险管控 + 可审计"。
**可执行代码隔离**：若未来需让 Agent 跑本地脚本，用受限子进程+资源限额，不引 microVM。

---

## 建议落地顺序（与 ZCode 第一波/P1 兼容，不冲突）

| 波次 | 内容 | 对应层 | 状态 |
|---|---|---|---|
| 第一波（P0） | 接入 **univer** 办公操作面 | 办公操作面 | ✅ **已落地并装机** |
| 第二波（P1） | **本地工具市场**（treg 理念本地化） | 工具市场 | ✅ **已落地并装机** |
| 第二波（P1） | **kev 决策判断器**试点 | 决策模型 | ⏳ 未动（前置：核模型权重商用授权） |
| 第三波（P2） | ax 理念→出站白名单；浏览器自动化（本地优先） | 编排 / 真实浏览器 | ⏳ 未动 |
| 不抄 | substrate（零 Docker 冲突）、jev 手机副驾（第三方权益） | — | — |

---

## 附：商用授权审计（2026-09-24，本轮新增）

定位新增「**可商用**」后，对**已落地的 office 链路**做了全量依赖审计：

| 项 | 结果 |
|---|---|
| 扫描范围 | `tools/office-bundle/node_modules` **含传递依赖共 126 个真实包**（另 5 项 rxjs 子路径解析文件 `ajax/fetch/operators/testing/webSocket` 无独立授权，继承根包 Apache-2.0，已排除计数） |
| 授权分布 | MIT 79 / Apache-2.0 28 / BSD-3-Clause 9 / ISC 9 / 0BSD 1 |
| copyleft（GPL/AGPL/LGPL/SSPL） | **0 个** ✅ |
| 未知授权 | **0 个** ✅ |
| 结论 | **全部宽松授权，可商用无阻** ✅ |
| `@univerjs/*` 本体 | Apache-2.0（`@univerjs/icons` 为 MIT） |
| **数据外联审计** | 对打好的 12.0 MB `univer.bundle.js` 扫描全部 760 个 URL：**无任何 telemetry/analytics/埋点地址** ✅ |

**审计已脚本化（可复跑、CI 友好）**：
```bash
python scripts/audit_licenses.py --pkg tools/office-bundle \
    --bundle web/vendor/univer/univer.bundle.js
# 通过 exit 0；发现 copyleft/未知授权/外联告警 exit 1
```
后续引入新依赖（**尤其 kev 的模型权重**）都应先跑一遍。

**两个值得记录的细节**：
1. 依赖里有 `@univerjs/telemetry`，名字容易引起警惕。实查其实现**只是一个 DI 令牌**
   （`ITelemetryService = createIdentifier("telemetry.service")`），**无实现、无端点、无发送逻辑**——
   只有宿主主动注入实现才生效，MiniYuxi 不注入 → **零上报**。
2. bundle 里出现频次最高的外联域名是 `support.microsoft.com`（509 次），是**公式错误码的 Excel 文档链接**（常量字符串），不是网络请求；`www.w3.org`（219 次）是 XML/SVG 命名空间。均无运行时外呼。

> 建议：把这段审计做成**可复跑脚本**，纳入"每次引入新依赖"的检查清单（尤其 kev 模型权重）。

---

## 附：一个顺带查实的功能缺陷（SUM/AVG 不计算）

审计依赖时顺带定位到已挂账的缺陷，**根因已查实**（此前只知"没配 workerURL"，现在知道是**设计使然**）：

`@univerjs/preset-sheets-core` 的 preset 工厂函数里有这么一段：
```js
function <SheetsCorePreset>(t = {}) {
  let { container = "app", workerURL: n, ... } = t,
      v = !!n;                                   // v = 是否提供了 workerURL
  return { plugins: [
    v ? [RpcMainThreadPlugin, { workerURL: n }] : null,
    [SheetsFormulaPlugin, { notExecuteFormula: v }],   // ← 关键
    ...
  ]};
}
```

**`notExecuteFormula: v`——没给 `workerURL` 时，preset 会主动把公式执行关掉**（公式只注册、不求值）。
所以 HR 表格里 SUM/AVG 不计算不是 bug，是"未启用公式执行"的既定行为。

**修法（已落地 ✅，2026-09-24）**：`@univerjs/preset-sheets-core/worker` 有独立 worker 入口，
导出 `UniverSheetsCoreWorkerPreset`（内含 `UniverFormulaEnginePlugin` + `UniverRPCWorkerThreadPlugin` + `UniverRemoteSheetsFormulaPlugin`）。

| 步骤 | 内容 | 状态 |
|---|---|---|
| 1 | 新增 worker 入口 `tools/office-bundle/src/office-worker-entry.js`（只 import worker preset，**不含任何 UI/CSS**——Worker 里没 DOM） | ✅ |
| 2 | `build.mjs` 改为出两个产物 → `univer.bundle.js`（12.0 MB）+ **`univer.worker.js`（8.9 MB）**，均为 IIFE（classic worker 需要） | ✅ |
| 3 | `api.py` 加静态路由 `/vendor/univer/univer.worker.js` | ✅ |
| 4 | `web/office/office-host.js` 里 `UniverSheetsCorePreset({container, workerURL:'/vendor/univer/univer.worker.js'})` | ✅ |

**验证（Playwright，8/8 通过）**：

| 断言 | 结果 |
|---|---|
| 登录 / 主页面 / office-host.js 加载 | ✅ |
| 表格 canvas 渲染 | ✅ |
| **公式引擎 Worker 被创建**（`page.on('worker')` 捕获到 `/vendor/univer/univer.worker.js`） | ✅ ← 证明 `workerURL` 接线生效 |
| Worker 脚本可实例化、无致命错误 | ✅ |
| **`=SUM(A1:A3)` 求值 = 6**（A1=1,A2=2,A3=3，轮询 ~1.5s 等 worker RPC 返回） | ✅ ← 证明公式真的算 |
| pageerror | ✅ 0 条 |

截图存证：`docs/_shots/miniyuxi-univer-20260924/03-formula.png`

> ⚠️ 注意：`workerURL` **不是性能优化项，是功能开关**。缺了它 preset 会把 `notExecuteFormula` 置 true，
> 表格静默退化成"只能填数字不能算"。日后若重构 office 集成，务必保留这一项。

> 注：以上与已落地的 **ZCode 逆向第一波+P1**（Command/知识库引用/子智能体）**互不冲突**，是 MiniYuxi 能力的纵向扩展（基础设施层），ZCode 是横向功能（Agent 能力）。

---

## 拍板结果与落地状态（2026-09-24 更新）

### 阿长拍板
1. 是否同意"吸收理念、本地化实现、红线拒绝"总方针 → **同意** ✅
2. 第一波是否从 univer 办公操作面动手 → **是** ✅
3. 是否要先出具体改造方案 + 代码落地 → **直接落地** ✅

### ⚠️ 定位更正（2026-09-24 阿长补充，**覆盖本文档初版前提**）

**MiniYuxi 的定位是「企业级 Agent：数据可以出本机、零 Docker、可商用」。**

本文档初版把"数据不出本机"当成硬约束写进了结论与决策表，并据此否掉 treg / 手机副驾——
**该前提已作废**，全文相关推理已按上表重推。核心变化：
- ❌ 删掉："数据不出本机/不出境"这条红线
- ✅ 改为三条把关轴：**零 Docker（底座）/ 可商用（授权）/ 第三方权益**
- ✅ 放开：云端 LLM/API、云端微调、云端浏览器智能体
- 🟡 保留但换理由：出站白名单/HITL（从"合规阻断"→"成本与风险管控 + 可审计"）
- ✅ **已落地**：**数据出境开关 + 出境日志**（0.4.0）——企业级不再是"全开/全关"
- ✅ **已修**：版本号统一为唯一来源 `core/version.py`（原三源漂移）

### 落地状态

| 波次 | 层 | 状态 | 装机版 |
|---|---|---|---|
| 第一波 P0 | **univer 办公操作面** | ✅ **已落地并装机** | ✅ 已生效 |
| 第二波 P1 | **本地工具市场**（treg 理念本地化） | ✅ **已落地并装机** | ✅ 已生效 |
| 第二波 P1 | **数据出境开关 + 出境日志**（企业级定位落地） | ✅ **已落地并装机**（0.4.0） | ✅ 已生效 |
| 第二波 P1 | kev 决策判断器（本地"合规判断专家"） | ⏳ 未动（阿长本轮未选） | — |
| 第三波 P2 | ax 出站白名单 / 本地 Playwright | ⏳ 未动 | — |
| 不抄 | substrate、jev 手机副驾 | — | — |

**装机版 sidecar md5**：`08673bc71f60cd38a041707413e824ed`（v0.4.0，63138708 B）
—— `C:\Program Files\MiniYuxi\binaries\` 三份同名文件一致。
上一版（0.3.0）备份在 `binaries\_backup-20260924-egress\`。

> ⚠️ **装机目录勘误（本轮新发现）**：`C:\Program Files\MiniYuxi\` **根目录**下还有两份 9/23 的旧 sidecar
> （52 MB ×2），但 `apps/desktop/src-tauri/src/lib.rs` 里 `SIDECAR_NAME = "binaries/miniyuxi-sidecar"`
> 决定了实际加载的是 **`binaries\` 子目录**；`spawn_sidecar()` 只有两条路径（开发态 `MINIYUXI_SIDECAR_PY`
> / 打包态 `.sidecar("binaries/miniyuxi-sidecar")`），**没有任何回退会用到根目录那两份**。
> 它们是历史安装布局的残留死重（约 104 MB），可择机清理。

### P0 univer 办公操作面 —— 交付明细
- **打包**：`tools/office-bundle/`（esbuild IIFE，minify + es2020）→
  `web/vendor/univer/univer.bundle.js`（12.0 MB）+ `univer.bundle.css`（116 KB）。
- **后端**：`core/office.py`（`office_docs` 表）+ `api.py` 四条 CRUD 路由
  （`/api/office/save|list|{doc_id}` GET/DELETE）+ 四条静态路由（**不回退 CDN**，未构建时 503 + 构建指引）。
- **前端**：`web/office/office-host.js`（懒加载 Univer → 全屏 overlay → 表格/文档切换 → 存档 CRUD）+
  `office-host.css`（明暗双主题）；`wb_workbench.js` 顶部导航「办公套件」入口。
- **验证**：`core/office.py` CRUD + 租户隔离 16/16 ✅；Playwright E2E 13/13 ✅；
  装机版实测 CRUD 全通（save→read→list→delete→404）✅；静态资源 4/4 HTTP 200 ✅。
- **截图存证**：`docs/_shots/miniyuxi-univer-20260924/01-sheet.png`（表格）、`02-doc.png`（文档）。

### P1 本地工具市场（treg 理念本地化）—— 交付明细
- **合规边界**：只做**本地 SQLite 只读浏览 + 启停**；**不接 treg 服务、不注入远程凭据、不拉远程工具目录**。
- **后端**：`core/tools_registry.py` 补 6 列（`category/tags/risk/source/requires_approval/updated_at`）+
  `list_market/get_market/toggle_market/list_categories`；`api.py` 三条 `/api/market/*` 路由（toggle 写 audit）。
- **前端**：`wb_workbench.js` 顶部导航「工具市场」→ 抽屉（分类标签条 + 工具卡片 + 启停开关）；
  `wb_workbench.css` 追加 `.mkt-*` 样式。
- **验证**：市场单测 18/18 ✅；对真实坏库副本的自愈测试 18/18 ✅；装机版实测分类
  `knowledge=2 / utility=2 / web=1`、`?category=web` → `web_search`、toggle 关/开均返回正确 ✅。

### 关键坑（已写入技能 `miniyuxi-module-scaffold`）
1. **SQLite `ALTER TABLE ADD COLUMN` 不允许非常量默认值** —— `DEFAULT (datetime('now'))` 在已填充库上必失败，
   被 `try/except: pass` 静默吞掉 → 列不存在 → 后续 `UPDATE ... SET updated_at=...` 全部静默失败。
   改用常量默认 `TEXT DEFAULT ''`。**空表测通过不算通过，必须拿真实数据量的库副本测。**
2. **FastAPI 裸标量参数 = query 而非 body** —— `enabled: bool = True` 要走 `?enabled=false`；
   发 JSON body 会被忽略取默认值，误判为"接口 bug"。
3. **验证装机版最硬的手法**：`PyInstaller.archive.readers.CArchiveReader` 从 exe 归档 extract 出文件比 md5，
   比起服务打接口更确定（本轮 4/4 逐字节一致）。

---

## 落地前已核验
- 开源协议：univer（Apache-2.0）、treg 仅取理念不引入代码。
- 接口稳定性：ax/substrate/kev 均"早期"，本波未引入其组件。
