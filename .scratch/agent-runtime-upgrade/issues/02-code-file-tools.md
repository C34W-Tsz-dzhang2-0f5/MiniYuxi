# 02 · 代码 / 文件工具（file.write + code.gen_tool，HITL + 白名单）

Status: `ready-for-agent`
Depends on: —
Owner: —

## 目标
让「在对话框写代码 / 写文件」**真正可执行**。当前工具清单无任何文件/代码工具，`coding_agent` 只暴露成 REST 端点未进工具链。

## 契约
- 新增 `@tool("file.write", ..., toolset="file", requires_approval=True)`：入参 `{path, content}`，落盘前过 `core/security.py` 敏感路径黑名单 + 工作空间白名单；**默认仅 `allow_full_access=True` 时可用**。
- 新增 `@tool("code.gen_tool", ..., toolset="file", requires_approval=True)`：包装 `coding_agent.generate_tool`，让 Agent 能生成可复用工具（走 HITL）。
- 一律经 `tools_registry.run_tool_governed()`（egress/HITL/熔断/审计），**禁止旁路**。

## 安全红线（🔴）
- 写文件是**不可逆动作** → `requires_approval=True`，走 `approval` 审批卡，**禁止模型自审**。
- 路径必须过白名单（工作空间根）**且**过 `security.py` 黑名单（`C:\Windows`、`System32`、`.ssh`、`*.key` 等）。
- `allow_full_access=False` 时 `file.write` 直接拒绝。

## 验收（先写失败测试）
- [ ] `tests/_verify_file_tools.py`：写白名单内成功 / 写黑名单被拒 / 越权路径被拒 / 无审批不执行（HITL 挂起）。
- [ ] `code.gen_tool` 触发审批卡，续跑才落地。
- [ ] 接入 `scripts/verify.py` quick 子集。
- [ ] S4：对话框「帮我写个 a.txt 内容 xxx」→ 弹审批 → 确认 → 文件真出现在工作空间。

## Done
- commit: _（实现后填）_
