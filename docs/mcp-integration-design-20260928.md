# MiniYuxi × RuoYi 业务底座 MCP 集成设计（Option 1，内核不变）

> 文档状态：设计稿 v1（2026-09-28）
> 输入来源：豆包帖《MiniYuxi 内核不变下的优化方案》（thread xMl1DQiixvg7cla1Y）+ 微信文《OA/ERP/CRM/HRM 到底怎么配合》（mp.weixin.qq.com/s/5On3L8DzFLWmJ2GQxaRfWg）+ 对 MiniYuxi 当前代码的逐行核验。
> 一句话结论：**架构方向正确、优于 N8N 基线，但"零内核改动"是误判——需改 3 个非指纹 core 文件 + 新建 MCP-Adapter 微服务；红线（不碰 db/rag/agent）守得住。**

---

## 0. 结论先行

| 结论项 | 判定 |
|---|---|
| 用 MCP-Adapter 封装 RuoYi 替代/补充 N8N 直连 | ✅ 采纳（MVP 推荐，解决双源配置不同步） |
| "MiniYuxi 原生已具 mcp_client，加一条 connectors 记录即零改动" | ❌ **误判**（见 §3 实测） |
| 落地需修改内核 | ⚠️ 需改 `mcp_client.py` / `connectors.py` / `tools_registry.py`，但**三者均非指纹文件**（指纹 = `db.py`/`rag.py`/`agent.py`），红线可守 |
| 需新建组件 | ✅ MCP-Adapter 微服务（Go/Python，封装 RuoYi OpenAPI） |
| HITL 审批 + 审计能否自动接管 MCP 工具 | ✅ `run_tool_governed` 已接 `approval` + `soc_audit`，MCP 工具带 `requires_approval=True` 即自动生效（当前 mcp_client 未传，需补） |

**工作量重估**：豆包帖原估"MVP 可控"，实际 MiniYuxi 侧约 1 个中等改造 + Adapter 1 个中等~大型微服务，**比原估低估约一档**，但仍在非指纹红线内，无架构返销风险。

---

## 1. 业务边界（来自微信文，作为工具面设计依据）

微信文（帆软/简道云软文，方法论 vendor-neutral 可用）的核心论点，恰好为技术集成提供业务蓝图：

### 1.1 四系统分工（底座 RuoYi-Office-Vben 内部）
- **CRM 管客户**：线索→客户→商机→报价→合同（管"客户能不能拿下来"）。
- **ERP 管经营/履约**：销售订单→库存/采购/生产→发货→应收（管"拿下来后能否按时交货回款"）。
- **HRM 管人**：员工→部门→岗位→考勤→绩效→薪酬（人员与组织的基础数据源）。
- **OA 管流程**：申请→审批→行政→通知→跨部门协作（管"这件事能不能做"）。

### 1.2 真正要打通的是 4 类核心数据（不是 4 套软件）
1. **人员&组织数据**（HRM → OA/其他流程直接复用，不重录）。
2. **客户数据**（CRM 形成 → 订单/履约继续用，避免 CRM/ERP/财务三套客户名对不上）。
3. **订单&业务数据**（签单 → 关联库存/采购/生产/发货/回款，管理层能从"签多少"看到"交多少收多少"）。
4. **审批结果**（最关键易忽略）：**"审批通过 ≠ 业务结果"**——审批后要传递"下一步谁继续做"，而非仅一个"已通过"状态。

### 1.3 对集成的硬性启示（写入本设计）
- **MiniYuxi / MCP-Adapter 不碰业务库**：增删改查、事务、库存、审批全部由 RuoYi 底座完成（印证豆包帖红线）。
- **Agent 侧不另存业务副本**：避免"数据录三遍"，也契合 egress 不落本地副本的合规取向。
- **`confirm_required` 挂在"审批后下一步执行"边界**：这是 HITL 挂点的业务依据。
- **工具面按 4 类数据 + 3 条业务链编排**（见 §5），而非按系统堆接口。

> ⚠️ 注意：微信文推的"简道云模板"是帆软广告，本设计对接底座是 **RuoYi-Office-Vben**，勿混淆。

---

## 2. 技术架构（来自豆包帖，方案选型）

### 2.1 方案一：MCP-Adapter 封装 RuoYi（**MVP 推荐**）
- RuoYi 业务能力包装成标准 MCP 服务；MiniYuxi 用原生 `mcp_client` 对接。
- 工具元数据（name/描述/入参 schema/risk/confirm_required/角色白名单）**全部定义在 Adapter 侧**，MiniYuxi 自动拉取 → **单一数据源，消除双源配置不同步**。
- 身份透传：`mini_yuxi_user_id` ↔ RuoYi token，token 加密存 Adapter，MiniYuxi 永不直接持 RuoYi 原始 token。
- **短板**：弱于复杂工作流编排（重试/分支/定时不如 N8N），适合 MVP / 自研底座对接。

### 2.2 方案二：MCP-Adapter + N8N 混合总线（生产级终态）
- N8N 干"外部脏活"（厂商 API 差异/OAuth/分页/重试/告警/事件流）；MCP-Adapter 干"工具标准化"；MiniYuxi 只消费标准 MCP。
- 代价：多一层服务，MVP 过重。**演进路线**：先方案一，后期接大量第三方 SaaS 时升方案二。

### 2.3 横向对比
| 方案 | 维护复杂度 | 工具元数据来源 | 新增业务系统改动点 | 适用 |
|---|---|---|---|---|
| 基线A 直连 RuoYi | 高 | SKILL.md 双源 | 改 connectors 代码 | 快速 Demo，不建议上产 |
| 基线B +N8N | 中 | SKILL+N8N 双源 | 配 N8N 流程+改 SKILL | 多 SaaS，元数据易不同步 |
| **方案1 MCP-Adapter（推荐 MVP）** | 中低 | MCP 服务单一源 | 配/开发 Adapter，仅改 DB 表 | 自研底座 MVP，最优 PoC/准产 |
| 方案2 MCP+N8N 混合 | 较高 | MCP 服务单一源 | N8N 流程+MCP 注册 | 正式生产，多异构系统 |

---

## 3. 代码实测纠正（关键，决定"零改动"是否成立）

以下为对 `E:/HR有关AI/AI应用基座最佳实践/14_自研MiniYuxi` 当前代码的逐行核验结果（非印象）：

| 豆包帖断言 | 代码实测（file:line） | 判定 |
|---|---|---|
| 原生具备 `mcp_client.py` | `core/mcp_client.py` 确实存在 | ✅ 真 |
| 直连远程 SSE MCP 服务 | 全文件仅 `subprocess.Popen` stdio（:19），**无任何 SSE/HTTP/streamable** | ❌ 假 |
| `connectors` 加一条 MCP 类型记录即可 | `connectors.py:19` `KINDS=("wecom","wechat","crm","erp","feishu")`，**无 mcp**；`register()` 非法 kind `raise ValueError` | ❌ 假 |
| `mcp_client` 已预留解析 `_meta`(risk/confirm_required) | `discover_tools()`(:75) 只取 name/description/inputSchema，**不读 `_meta`** | ❌ 假 |
| discover 自动发现业务工具 | `_server_cmd()`(:70) 硬编码连本地 `tools/mcp_readonly_fs.py`，**不读 connectors 表** | ❌ 假 |
| HITL/审计自动接管 MCP 工具 | `tools_registry.run_tool_governed`(:305) 已接 `approval.needs_approval` + `soc_audit`；但 `_register_mcp`(:94) **未传 requires_approval** → 默认不挂审批 | ⚠️ 能力在，没接上 |

**实测小结**：当前 `mcp_client.py` 是一个**面向内置只读文件系统的 stdio 玩具客户端**，不具备生产集成所需的远程传输、元数据解析、connectors 驱动能力。因此"零内核改动"不成立。

**红线判定**：需改的 `mcp_client.py` / `connectors.py` / `tools_registry.py` **均不在指纹文件清单**（指纹 = `db.py`/`rag.py`/`agent.py`），扩展这三者**不破红线**。豆包帖"不碰指纹"约束可满足，只是不能"零改动"。

---

## 4. 落地改造清单

### 4.1 MiniYuxi 侧（非指纹，可守红线）
- **A1 · 远程传输**：`mcp_client.py` 新增 SSE/HTTP（Streamable HTTP）传输模式，支持连接网络部署的 MCP-Adapter（替代硬编码本地 stdio）。保留 stdio 作为本地工具通道。
- **A2 · `_meta` 解析**：`discover_tools()` 读取 MCP 工具 `_meta` 扩展字段（risk / confirm_required / role_whitelist），透传给注册层。
- **A3 · connectors 驱动**：`connectors.py` `KINDS` 增加 `"mcp"`；`register()` 放行；`mcp_client` 改为**从 connectors 表读取 MCP 服务配置**（SSE 地址/认证），替代 `_server_cmd()` 硬编码。
- **A4 · 注册元数据**：`tools_registry.register` 增加 `risk` / `requires_approval` 形参（或扩展 meta dict）；`run_tool_governed` 已支持审批+审计，无需改。
- **A5 · egress 收口**：远程 MCP 调用经 `core/egress.py` 出境白名单管控（当前 stdio 本地通道不经过 egress，远程须补）。

### 4.2 MCP-Adapter 侧（新建独立微服务，Go/Python 均可）
- **B1 · 封装 RuoYi OpenAPI**：将 OA/CRM/ERP/HRM 业务接口封装为标准 MCP Tools，工具名按 §5 分组。
- **B2 · `_meta` 扩展**：每个工具在 `_meta` 声明 `risk`(info/warn/high_risk) 与 `confirm_required`(bool)；high_risk 工具**仅返回预览数据，拒绝直提交**，等待 HITL。
- **B3 · 身份映射**：`mini_yuxi_user_id` ↔ RuoYi 业务 token；RuoYi token **加密存储**于 Adapter，MiniYuxi 永不直接持原始 token；双层鉴权（Adapter 参数校验 + RuoYi 业务权限校验）。
- **B4 · 异常处理/脱敏/健康**：请求代理、异常封装、`_meta` 脱敏规则、SSE 服务健康检查。

### 4.3 connectors 表 mcp 记录样例
```json
{
  "id": "mcp:ruoyi-office",
  "name": "RuoYi-Office-Vben 业务底座",
  "kind": "mcp",
  "enabled": 1,
  "config_json": {
    "transport": "sse",
    "endpoint": "https://mcp-adapter.internal/sse",
    "auth": { "type": "bearer", "env": "MCP_ADAPTER_TOKEN" },
    "egress_class": "connector"
  },
  "status": "unknown"
}
```

### 4.4 MCP-Adapter 最小原型骨架（Python 伪代码）
```python
# mcp_adapter.py —— 封装 RuoYi OpenAPI 为标准 MCP 工具，输出 _meta 扩展
from mcp.server import Server
from mcp.server.sse import SseServerTransport

app = Server("ruoyi-office-adapter")

TOOLS = [
  {
    "name": "erp.create_sales_order",
    "description": "生成销售订单（高危写操作）",
    "inputSchema": {...},
    "_meta": {"risk": "high_risk", "confirm_required": True,
              "note": "仅返回预览，HITL 确认后才真提交 RuoYi"}
  },
  # ... crm/oa/hrm 各组工具
]

@app.list_tools()
async def list_tools(): return TOOLS

@app.call_tool()
async def call_tool(name, args):
    if TOOLS_BY[name]["_meta"].get("confirm_required") and not args.get("__approved"):
        return preview_only(name, args)          # 高危：只返预览
    return await ruoyi_proxy(name, args)          # 经身份映射调 RuoYi
```

---

## 5. MCP 工具面蓝图（按 4 类数据 + 3 条业务链编排）

> 设计原则：工具元数据**单一源**（Adapter `_meta` 定义），MiniYuxi 自动拉取；Agent 侧 SKILL.md 只留意图触发，不再维护 API schema。

| 数据类 | 工具（建议） | 类型 | risk | confirm_required | 说明 |
|---|---|---|---|---|---|
| **人员&组织（HRM）** | `hrm.get_employee` / `hrm.list_org` | read | info | 否 | 只读代理，Agent 不另存副本 |
| **客户（CRM）** | `crm.search_customer` / `crm.get_customer` | read | info | 否 | 客户主数据复用 |
| | `crm.create_lead` | write | warn | 否 | 线索非单据，低风险写 |
| | `crm.create_contract_draft` | write | warn | 视阈值 | 合同草稿 |
| **订单&履约（ERP）** | `erp.check_inventory` | read | info | 否 | 库存查询 |
| | `erp.create_sales_order` | write | **high_risk** | **是** | 真·单据，Adapter 仅返预览 |
| | `erp.create_purchase_order` | write | **high_risk** | **是** | 采购单，同上 |
| | `erp.get_ar_receivable` | read | info | 否 | 应收查询 |
| **审批&流程（OA）** | `oa.submit_approval` | write | warn | 视金额阈值 | 提交审批 |
| | `oa.get_approval_status` | read | info | 否 | 审批状态 |
| | `oa.approval_handoff` | read→trigger | warn | **是** | **关键**：返回"下一步谁继续做"，触发下游 ERP/OA 执行（审批≠业务结果） |

**3 条业务链（Agent 编排示例）**：
1. **CRM→ERP 订单交接**：`crm.get_customer` → `erp.check_inventory` → `erp.create_sales_order`(high_risk+HITL) → 发货/回款跟踪。
2. **OA→ERP 采购交接**：`oa.submit_approval` → `oa.approval_handoff`(HITL 确认) → `erp.create_purchase_order`(high_risk+HITL) → 到货/验收/入库。
3. **HRM→OA 入职交接**：`hrm.get_employee` → `oa.submit_approval`(办公用品/账号/设备) → 自动接上考勤/绩效。

---

## 6. 红线与约束（不可突破）

1. `core/db.py` / `core/rag.py` / `core/agent.py` **禁止修改**（指纹文件；本次改造只动 mcp_client/connectors/tools_registry，合规）。
2. 所有外部网络请求（含远程 MCP 调用）**必须经 `egress.py` 出境闸门**（A5）。
3. 业务增删改查/事务/库存/审批**全部由 RuoYi 底座完成**，Agent/Adapter 不操作业务库。
4. 高危写操作**仅返回预览，禁止直提交**；HITL 人工确认机制保留（`approval.py` + `run_tool_governed` 已就位）。
5. 审计：每次工具调用（含被拒/被拦/挂起）落 `soc_audit`（已就位，无需改）。

---

## 7. 风险分级

| 项 | 风险 | 敞口 / 缓解 |
|---|---|---|
| 误信"零改动"直接上 → 连不上远程 MCP、工具无 risk/HITL | 🔴 高 | 本设计已纠正；按 §4 改造后再上 |
| MiniYuxi 侧 mcp_client SSE+`_meta`+connectors 改造 | 🟡 中 | 约 1 个中等工作量，非指纹可守红线 |
| 新建 MCP-Adapter 微服务（封装 RuoYi + 身份映射 + 加密存 token） | 🟡 中~大 | 独立服务开发，非 MiniYuxi 内核 |
| 底座混淆（简道云 vs RuoYi） | 🟡 中 | 本设计明确底座=RuoYi-Office-Vben |
| 方向本身 | 🟢 低 | 架构合理，推荐采纳 Option 1 |

---

## 8. 落地顺序与部署校验清单

### 8.1 落地顺序
1. **MVP（方案1）**：完成 A1–A5 + B1–B4；验证 Agent 自然语言调 OA/CRM/ERP/HRM 工具 + HITL + 审计 + egress 闭环。
2. **演进（方案2）**：接入大量第三方 SaaS / 复杂定时 / 事件流时，叠 N8N 混合总线。

### 8.2 部署校验清单
- [ ] MiniYuxi：`mcp_client` SSE 连通 Adapter；`discover_tools` 拉到 N 个工具；`_meta` 解析生效。
- [ ] 高风险工具 `requires_approval=True` 自动挂 HITL 弹窗；调用落 `soc_audit`。
- [ ] 远程 MCP 地址已加入 `egress.py` 出境白名单；默认全放行策略下可审计。
- [ ] Adapter：连 RuoYi OpenAPI 成功；`mini_yuxi_user_id↔token` 映射正确；token 加密存储。
- [ ] high_risk 工具拒直提交，仅返预览；SSE 服务健康检查通过。
- [ ] 端到端：Agent 自然语言 → `oa.submit_approval` → HITL 确认 → `oa.approval_handoff` → `erp.create_purchase_order`(HITL) → 真提交 RuoYi → 全链路审计留痕。

---

## 9. 附：输入材料索引
- 豆包帖《MiniYuxi 内核不变下的优化方案》：thread xMl1DQiixvg7cla1Y（技术架构 / 方案1·2 / 对比表）。
- 微信文《OA/ERP/CRM/HRM 到底怎么配合》：mp.weixin.qq.com/s/5On3L8DzFLWmJ2GQxaRfWg（业务边界 / 4 类核心数据 / 审批≠业务结果）。
- 代码核验：`core/mcp_client.py` / `core/connectors.py` / `core/tools_registry.py` / `api.py:572,1309`（本设计 §3 所有判定均来自实读）。

---

## 10. 执行记录（2026-09-28）

> 阿长指示"按设计文档执行"。以下为 Option1 MVP **MiniYuxi 侧（A1–A5）+ 生产级 MCP-Adapter（B1–B4 全量）+ 网页版/桌面版前端业务集成面板** 的落地与验收结果。
> 生产级 Adapter 已全量落地（真实 RuoYi OpenAPI 封装 + 身份映射加密 + 异常/脱敏/健康），并配置驱动：无真实实例时 `MCP_RUOYI_MODE=mock` 内置数据保证不挂；填 `RUOYI_BASE_URL/USER/PASS` 即连真实 RuoYi（§8.2 端到端待真实环境串联）。

### 10.1 改造落地清单（均已落到代码）

| 项 | 文件 | 改动要点（file:line 已实读核验） | 红线 |
|---|---|---|---|
| **A1 远程 SSE 传输** | `core/mcp_client.py` | 新增 `MCPClientSSE`（:129）：JSON-RPC over SSE（2024-11-05），`GET /sse`→`endpoint` 事件取 POST 地址，线程 reader + id 关联收响应；零新增依赖（stdlib `urllib`+`http.server`）。保留原 stdio `MCPClient` 向后兼容 | ✅ 非指纹 |
| **A2 `_meta` 解析** | `core/mcp_client.py` | `discover_connector_tools()`(:286) 读取工具 `_meta` 的 `risk`/`confirm_required`，透传 `tools_registry.register(risk=, requires_approval=)` | ✅ 非指纹 |
| **A3 connectors 驱动** | `core/connectors.py` | `KINDS` 加入 `"mcp"`(:19)；`register()` 放行；`health()`(:70) mcp 视为就绪；`send_message()`(:93) mcp 返回 `not_applicable`（工具调用走 mcp_client SSE） | ✅ 非指纹 |
| **A4 注册元数据** | `core/tools_registry.py` | `register()`(:247) 增 `risk="info"` / `requires_approval=False` 形参并落 `_REGISTRY`；`list_tools()`(:376) 合并 `discover_connector_tools()` 并外露 `risk`/`requires_approval` | ✅ 非指纹 |
| **A5 egress 收口** | `core/mcp_client.py` | `_make_sse_handler()`(:258)：调用前经 `egress.guard("connector", endpoint, args, level="internal", tenant_id)`；被拒返回降级文案不崩链路 | ✅ 非指纹 |
| **B1 真实 RuoYi 客户端** | `tools/mcp_ruoyi_adapter.py` | `RuoYiClient`(:252)：配置驱动 `base_url+login→token`；13 条业务路径 `ENDPOINTS`（若依风格默认，`RUOYI_ENDPOINTS` 可覆盖）；`request()` 路径参数替换 + 剥离 `__` 内部键 + 脱敏 + 异常封装 | 新建独立文件 |
| **B2 `_meta` 风险 + 高危预览** | `tools/mcp_ruoyi_adapter.py` | `TOOLS`(:80) 13 工具带 `risk`/`confirm_required`；high_risk（`erp.create_sales_order`/`create_purchase_order`）**默认仅返预览**，仅 `__commit=true`（HITL 续跑注入）才真提交 | 新建独立文件 |
| **B3 身份映射 + Token Vault** | `tools/mcp_ruoyi_adapter.py` | `TokenVault`(:186)：`mini_yuxi_user_id↔RuoYi token` Fernet 加密落 SQLite（明文不出进程）；密钥 `RUOYI_FERNET_KEY` 或 `.ruoyi_fernet_key`（chmod 600）；ruoyi 模式缺 `cryptography` 启动即报错不静默降级 | 新建独立文件 |
| **B4 异常/脱敏/健康** | `tools/mcp_ruoyi_adapter.py` | `desensitize()`(:157) 递归遮蔽 身份证/手机/邮箱/银行卡；`_Handler` SSE + `/healthz`(:413) 探针；统一异常不崩 | 新建独立文件 |
| **HITL 续跑闭环 + `__commit` 注入** | `core/tools_registry.py` | `run_tool_governed()`(:337) 续跑分支：已 approved 时跳过审批门直接执行；**高危/需确认工具续跑时注入 `__commit=True`**，Adapter 才真正提交（B2 防御纵深） | ✅ 非指纹 |
| **工具目录刷新** | `core/tools_registry.py` / `api.py` | 新增 `invalidate_mcp_cache()`(:381)；`GET /api/tools/list?refresh=1` 强制重做 SSE 发现（前端加完连接器即拉工具） | ✅ 非指纹 |
| **前端业务集成面板** | `web/wb_workbench.js` + `web/wb_workbench.css` | 新增 `openBizPanel()`：宽弹窗 = 左连接器管理（增/健康）+ 右 4 模块工具面（OA/CRM/ERP/HRM，风险徽标 + 参数表单 + 调用）；命中 HITL 弹审批卡（确认/拒绝 → `/api/approvals/{aid}/decide` → 带 `approval_id` 续跑）；`handleNavAction` 加 `case 'biz'`。网页/桌面共用 `web/`，桌面自动复用 | 新建/前端 |
| **端到端测试** | `tests/_verify_mcp_integration.py` | 离线条跑：临时 DB 隔离 + 起 adapter + 注册 mcp 连接器，15 项断言（含 HITL 续跑提交 + 脱敏 + 配置驱动 + Vault 加密） | 新建 |

**指纹文件零改动**：`core/db.py` / `core/rag.py` / `core/agent.py` 本次未触碰，红线守住。

### 10.2 验收结果（`tests/_verify_mcp_integration.py`，离线，exit 0）

| # | 验证点 | 结果 |
|---|---|---|
| 1 | SSE 连通并拉到远程 MCP 工具（含 `erp.create_purchase_order`） | ✅ PASS |
| 2 | 远程工具数量达标（**13 个**，覆盖 HRM/CRM/ERP/OA 全蓝图） | ✅ PASS |
| 3 | `_meta` 解析生效：采购单 `risk=high_risk` / `confirm_required=True` | ✅ PASS |
| 4 | high_risk 工具经 `run_tool_governed` 自动挂 HITL（`status=pending`） | ✅ PASS |
| 5 | 默认策略：`hrm.get_employee` 经 egress 放行并调用成功 | ✅ PASS |
| 6 | LOCKDOWN：远程 MCP 调用被 egress 拒绝并降级（不崩链路） | ✅ PASS |
| 7 | `egress_log` 记录 connector 出境（2 条） | ✅ PASS |
| 8 | HITL 续跑前置：审批单已建且 `pending` | ✅ PASS |
| 9 | 带 `approved_aid` 重调 → 不再 `pending`，直接执行 | ✅ PASS |
| 10 | **B2 防御纵深：续跑注入 `__commit`，Adapter 真正提交（`committed=True`，非预览）** | ✅ PASS |
| 11 | 防护：未带 `approved_aid` 重调同一高危工具 → 重新挂 HITL（不绕过审批门） | ✅ PASS |
| 12 | B4 脱敏：手机/邮箱/身份证被遮蔽 | ✅ PASS |
| 13 | B1 配置驱动：`RUOYI_ENDPOINTS` 覆盖合并（默认 13 条路径） | ✅ PASS |
| 14 | B3 TokenVault：Fernet 加密 roundtrip（明文不出进程） | ✅ PASS |
| 15 | B3 TokenVault：明文未落库（加密存储） | ✅ PASS |

**汇总：PASS 15 / 15（INTEGRATION_EXIT=0）。**

### 10.3 回归（确认未破既有能力）

| 检查 | 命令 | 结果 |
|---|---|---|
| 编译改动文件 | `py_compile core/tools_registry.py api.py`（+ 既有 `mcp_client.py`/`connectors.py`） | ✅ COMPILE_OK |
| MCP 集成端到端 | `tests/_verify_mcp_integration.py` | ✅ 15 通过 / 0 失败 |
| egress 闸门回归 | `tests/_verify_egress.py` | ✅ 56 通过 / 0 失败（EGRESS_EXIT=0） |
| Skills 契约回归 | `tests/_verify_skills_contract.py` | ✅ 45/45（SKILLS_EXIT=0） |
| 前端 JS 语法 | `node --check web/wb_workbench.js` | ✅ JS_SYNTAX_OK |

> 注：`tools_registry.register` 新签名向后兼容——既有调用方（`coding_agent.py`、其它测试）未传 `risk`/`requires_approval` 时不报错（默认 `info`/`False`）。
> 注：集成测试需绑定本地端口（adapter SSE server），在受限沙箱中运行需放开网络（`dangerouslyDisableSandbox`）。

### 10.4 结论与待办

- **结论**：Option1 MVP 的 **MiniYuxi 侧 + 生产级 Adapter（B1–B4 全量）+ 网页版/桌面版前端业务集成面板** 三段全部落地并验收通过（15/15 断言 + 4 项回归全绿）。闭环：SSE 连 Adapter → 拉 13 工具 → 解析 `_meta` → 注册 risk/HITL → 经 egress 出境 → 审计留痕 → 前端连接器管理 + 4 模块工具面 + HITL 审批卡。指纹文件零改动，红线守住。
- **待办（非本次阻塞）**：
  - [ ] 部署清单 §8.2 端到端（Agent 自然语言→OA→HITL→ERP 真提交）待真实 Adapter（`MCP_RUOYI_MODE=ruoyi` + 实例凭证）串联实测。
  - [ ] 演进方案二（N8N 混合总线）按 §2.2 路线，待多异构 SaaS 接入时启动。
  - [ ] Adapter 新依赖 `cryptography`（仅 `ruoyi` 模式用）已装；若分发冻结环境需在 `requirements.txt`/部署清单登记。
