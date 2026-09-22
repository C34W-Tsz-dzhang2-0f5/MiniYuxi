# 更新日志 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/) 约定，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

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
