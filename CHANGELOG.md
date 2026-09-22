# 更新日志 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/) 约定，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [0.2.1] - 2026-09-22

### Changed
- **O6 冷启动优化**：`core/db.py` 的 `sqlite_vec` 由顶层 import 改为 `connect()` 内延迟导入（会连带拖入 numpy）。
  `import api` 冷启动 **3309ms → 2349ms（约 -29%）**；`import core.db` 仅 33ms 且不再加载 numpy；向量功能不变（`vec_version()` 仍 v0.1.9）。

### Added
- **O7 工具调用审计留痕**：`run_tool_governed` 补齐安全分层最后一环（Hermes 原则⑪ audit），
  `success / rejected / blocked / pending / error` 五类结果全部写入 `soc_audit` 哈希链；审计失败静默降级，不阻断主流程。
- **O8 联网工具可选审批**：`web_search` 支持 `MINIYUXI_APPROVE_WEB_SEARCH=1` 开启 HITL 审批门
  （默认关闭，行为完全不变），用于管控对外查询内容与出口流量。
- `tests/test_kernel_optimizations.py`（8 passed）。

## [0.2.0] - 2026-09-22

### Added
- **CLI 端（P2）落地**：`cli.py` 薄客户端，直接 `import core` 复用内核（不经 HTTP）。
  - `chat` 交互式对话（`/exit` `/new` `/ctx`）、`ask` 单次问答（`--json`）、`doctor` 环境体检（`--full` 复用 `tests/selftest.py`）、`kb list|search|add`、`tools`、`skills`、`serve`。
  - **延迟导入内核**：`--help` / `version` 不触发冷启动（~0.4s vs 2.4s）。
  - Windows 启动器 `miniyuxi.bat`；`pyproject.toml` 提供 `miniyuxi` console script（`pip install -e .`）。
- `tests/test_cli.py`（8 passed），含「help 路径不得导入 core」的延迟导入守护测试。

### Changed
- `doctor` 中 LLM 凭证缺失由 FAIL 降级为 **WARN**（项目有离线兜底，不影响可用性）。

### Planned (路线图)
- Desktop 端（Tauri sidecar 复用内核）。
- 文档站（VitePress 在线阅读）。

## [0.1.0] - 2026-09-22

### Added
- 三端统一架构方案：`docs/三端统一架构与开源增长方案.md`（Web / Desktop / CLI 共享 `core/` 内核）。
- 网页端原型 `web/prototype/index.html`（三端切换可交互，WorkBuddy 设计）。
- 开源基建：MIT `LICENSE`、`README.md` / `README_en.md` 落地页、`CONTRIBUTING.md`、`SECURITY.md`、`.github/` 模板与 CI。
- Hermes 原则落地（B-1 工具治理 / B-4 Cron=Agent / B-5 安全分层）。

### Changed
- 性能与稳定性优化（O1–O5）：DB 并发韧性 pragma、`tools/list` 与 `skills/list` TTL/mtime 缓存、`health` 探测缓存、首页渲染缓存。

### Quality
- `tests/selftest.py` 20/20、`test_hermes_landing.py` 13 passed、`test_perf_optimizations.py` 5 passed。

### Planned (路线图)
- Desktop 端（Tauri sidecar 复用内核）。
- CLI 端（`miniyuxi` 薄客户端 + `doctor` 自检）。
- 文档站（VitePress 在线阅读）。
