# 安全策略 (Security Policy)

## 支持的版本

| 版本 | 状态 |
|---|---|
| 0.1.x（main） | ✅ 安全更新中 |

## 上报漏洞

**请勿在公开 Issue / Discussion 中披露安全漏洞。** 请通过以下方式私信上报：

- GitHub Security Advisory（仓库 → Security → Report a vulnerability）
- 或邮件至 security@example.com（占位，发布前替换为真实地址）

请在报告中包含：
1. 受影响版本与复现步骤；
2. 影响面（权限提升 / 数据泄露 / 命令执行等）；
3. 建议修复（如有）。

我们将在 **72 小时内**确认收到，并在修复后公开致谢（经你同意）。

## 已知安全边界与设计

- **默认密钥与口令**：`MINIYUXI_SECRET` 为开发默认值，`admin/admin123` 为默认口令——生产必须改。
- **工具命令隔离**：工具子进程**不继承** provider 凭证、SSH agent socket 或无关父环境变量，仅保留 shell 基础变量并将 `HOME` / `PWD` 限定到工作区（参考 learn-workbuddy `SECURITY.md`）。
- **命令策略分层**：`hardline_block`（不可恢复命令无条件拦截）→ `is_dangerous_command`（走审批）→ 路径/网络校验 → 审计哈希链。
- **数据隔离**：多租户数据按 `tenant_id` 隔离；跨租户访问返回 403。
- **密钥管理**：仓库不含任何密钥；真实 Key 仅经环境变量 / `.env`（已 gitignore）提供。

## 范围外（out of scope）

- 模型本身的产出偏见或事实错误（属上游 LLM 责任）。
- 用户自行将服务暴露于公网且未加反代 / HTTPS 导致的暴露。
