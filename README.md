# MiniYuxi · 企业级 AI 助手（三端统一 · 本地优先 · 零 Docker）

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Self-test](https://img.shields.io/badge/selftest-20%2F20-brightgreen)](tests/selftest.py)
[![Stars](https://img.shields.io/github/stars/C34W-Tsz-dzhang2-0f5/MiniYuxi?style=social)](https://github.com/C34W-Tsz-dzhang2-0f5/MiniYuxi/stargazers)

> **把 Agent 跑进企业工作流**——Web / Desktop / CLI 三端共享同一套内核，SQLite 单文件、零外部服务、可审计。
> 内核只写一次，三端只是外壳；工具、记忆、权限、审计天然一致。

![三端统一工作台原型](web/prototype/index.html)

## ✨ 核心特性

- 🌐 **三端统一内核**：Web（SPA）/ Desktop（Tauri sidecar）/ CLI（薄客户端）共用 `core/`，功能永远一致。
- 🏢 **多租户 + RBAC**：admin / editor / viewer 角色矩阵，租户数据隔离。
- 🤖 **Agent 编排**：ReAct 主循环 + 工具治理（toolset 过滤 + 审批门）+ 多 Provider 故障转移。
- 📚 **知识库 RAG**：BM25 + 向量 RRF 融合检索，中文 bigram 分词，sqlite-vec 零服务。
- 🛡️ **安全审计**：hardline 命令拦截 → 审批 → 路径校验 → append-only 哈希链。
- ⏰ **定时任务**：Cron = Agent 任务（fresh session 执行，未知类型 fail-closed）。
- 💾 **本地优先**：单 Python 进程、单 SQLite 文件，内存 65–70MB，备份即拷文件。

## 🚀 快速开始

### 🌐 Web 端（已可用）

```bash
git clone https://github.com/C34W-Tsz-dzhang2-0f5/MiniYuxi.git MiniYuxi && cd MiniYuxi
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # 填入 LLM_API_KEY / EMB_API_KEY
python run.py                                       # http://127.0.0.1:8801
python tests/selftest.py                            # 期望 20/20
```

默认账号：`default / admin / admin123`（**首次部署务必改密**）。

### 🖥️ Desktop 端（路线图中 · 复用内核作 sidecar）

Tauri 外壳加载同一 SPA，Python 内核以 sidecar 常驻本地；详见 [`docs/三端统一架构与开源增长方案.md`](docs/三端统一架构与开源增长方案.md) 第 3 节。

### ⌨️ CLI 端（路线图中）

`miniyuxi chat "..."` 直接 `import core` 或连同一 REST 契约；`miniyuxi doctor` 复用自检。

## 🏗️ 架构

```
Web / Desktop / CLI  ──┐
                        ├─→  FastAPI AppServer (api.py)  ──→  core/ 内核（单一可信源）
        localhost/HTTPS ─┘                              Agent·Tools·RAG·Memory·Security·Scheduler·Audit
```

完整三端分层、核心模块映射（对照 learn-workbuddy 24 课）与开源增长策略见 👉
**[`docs/三端统一架构与开源增长方案.md`](docs/三端统一架构与开源增长方案.md)**。

## ✅ 质量凭证

- `tests/selftest.py`：**20/20** 端到端通过
- `tests/test_hermes_landing.py`：13 passed（Hermes 原则落地）
- `tests/test_perf_optimizations.py`：5 passed（性能优化回归）
- 提交/PR 经 `.github/workflows/verify.yml` 卡点（未定义符号扫描 + 法条闸门）

## 🔒 部署与安全红线

> 仓库**不含任何密钥**；真实 Key 经环境变量或根目录 `.env`（已忽略）提供。

- 默认 `MINIYUXI_SECRET` 为开发值、`admin/admin123` 为默认口令——**生产务必改**。
- 仅绑定 `127.0.0.1`；对内/对外访问务必套 **nginx 反代 + HTTPS**。
- SQLite 单写者，小团队可用；公网/高并发建议换 Postgres。
- 定期备份 `data/miniyuxi.db`（含向量、审计链、账号）。
- 接真实模型（可选）：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`；不设 `EMB_API_KEY` 则仅 BM25，功能不中断。

## 🤝 贡献

欢迎 Issue / PR！详见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。提交前请跑：

```bash
python tests/selftest.py && python tests/test_hermes_landing.py && python tests/test_perf_optimizations.py
```

## 📄 协议

[MIT](LICENSE) © 2026 MiniYuxi Contributors.

---

⭐ **如果这个项目对你有帮助，请给个 Star 支持我们继续完善三端！**
