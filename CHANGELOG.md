# 更新日志 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/) 约定，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [0.2.2] - 2026-09-22

### Added
- **桌面端（P3）落地**：Tauri 外壳 + Python 内核作 **sidecar 常驻**。
  - `run.py --sidecar`：强制回环 127.0.0.1、自动选空闲端口、`MINIYUXI_SIDECAR_READY {...}` 契约（stdout + `data/sidecar.json` 双通道）、`POST /api/desktop/shutdown` 优雅停机、可选 stdin 看门狗（`MINIYUXI_SIDECAR_WATCH_STDIN=1`）。
  - `core/auth.make_token(payload, ttl=...)`：桌面本地长会话 token（默认 7 天，受 `MINIYUXI_SIDECAR_TOKEN_TTL_H` 覆盖）。
  - `core/config.DATA_DIR` 受 `MINIYUXI_DATA_DIR` 控制；`run.py::_frozen_bootstrap` 在 PyInstaller 冻结时自动落 `%LOCALAPPDATA%/MiniYuxi/data`，避免 BASE_DIR 变 `_MEIPASS` 临时路径。
  - `cli.py serve --sidecar`（透传给 run.py）。
  - `apps/desktop/`：Tauri 外壳（`src/` 启动壳 + `src-tauri/` 主进程 4 依赖）、`withGlobalTauri` 走 `window.__TAURI__`、权限收口 `shell:allow-execute` 只允许自己的 sidecar；图标用 Pillow 现成生成（含 macOS `.icns`）。
  - `scripts/build_sidecar.py`：PyInstaller 打 `<HOST_TRIPLE>-miniyuxi-sidecar` 到 `apps/desktop/src-tauri/binaries/`（Tauri externalBin 格式）。
  - `examples/desktop_tour/code.py`：离线贯通演示（拉起 sidecar → READY → health → me → chat → tools → 优雅关闭）**7/7 通过**。
  - `tests/test_desktop_sidecar.py`：**2/2 通过**（单元 ttl 生效 + 端到端 tour）。
  - `docs/desktop.md` + `apps/desktop/README.md`：通信契约、三条跑通路径、风险与验收清单。
- `docs/三端统一架构与开源增长方案.md` §3 / §7 / §8 回写 P3 落地状态（路线图打 ✅）。
- `apps/desktop/dev-env.sh`：Windows MSVC 开发环境脚本（`source` 即用，自动探测 MSVC / Windows SDK 版本）。
  绕开本机两个坑：① Git Bash 自带 GNU `link.exe` 抢在 MSVC 链接器前；② 缺 LIB/INCLUDE 导致 LNK1181。
  等价于 `vcvars64.bat` 但不依赖 `cmd.exe`（Bash 安全策略禁用）。

### Fixed
- **Tauri `externalBin` 命名规则写反**：实测规则是 `<entry>-<target triple>`（triple 作**后缀**），
  而非 `<triple>-<entry>`。cargo 报错 `resource path binaries\miniyuxi-sidecar-x86_64-pc-windows-msvc.exe doesn't exist` 后校准，
  已修正 `scripts/build_sidecar.py` 的产物命名，并订正 `docs/desktop.md` 中的说明。
- **内核健壮性（`core/db.py`）**：sqlite-vec 扩展不可用时仍无条件执行
  `CREATE VIRTUAL TABLE ... USING vec0(...)` → 抛 `no such module: vec0` **直接把启动干掉**，
  与 `_load_vec_extension`「加载失败不致命、降级 BM25」的设计自相矛盾。
  现改为先 `vec_available()` 判定，不可用就跳过建表并降级为纯 BM25/FTS5，失败原因打到 stderr。
  （该缺陷在未装 sqlite-vec、或 SQLite 未编译扩展支持的非冻结环境同样会触发。）
- **sidecar 打包漏件**：`sqlite_vec` 的 `vec0.dll` 是**数据文件**不是 `.pyd`，PyInstaller 默认不收集，
  冻结内核启动即崩。已加 `--collect-all sqlite_vec`；另补 `--add-data skills;skills`（技能目录要扫）。

### Quality
- `tests/test_desktop_sidecar.py` 2/2（含 tour 7 步全绿 7.6s）。
- 不破坏既有测试：`tests/selftest.py` 20/20 / `test_hermes_landing.py` 13 passed 仍可在原内核下继续运行。
- **桌面外壳真实编译通过**（本机 Windows MSVC）：
  - `cargo check` ✅（38s，占位 sidecar 后一遍过）
  - `cargo build` ✅（15m33s，产出 `src-tauri/target/debug/miniyuxi-desktop.exe`，17.4MB）
  - 环境：rustc 1.98.1 · MSVC 14.44.35207（cl 19.44.35229）· Windows SDK 10.0.26100.0
- **冻结内核（真 sidecar）同样 7/7 通过**：`examples/desktop_tour/code.py --exe <sidecar>`，
  产物 78.9MB，`health` 显示 `vec=sqlite-vec v0.1.9`（证明 `vec0.dll` 已随包），
  数据目录正确落在 `%LOCALAPPDATA%/MiniYuxi/data`，优雅关闭 exit=0。
- **可分发安装包已产出**：`src-tauri/target/release/bundle/msi/MiniYuxi_0.2.0_x64_en-US.msi`
  （84.3MB = 78.9MB Python 内核 + 4.5MB 外壳 + 资源）；release 主程序 4.47MB（LTO + strip）。

### Changed
- Windows 打包目标收为 **仅 `msi`**：Tauri 的 `nsis` 目标需从
  `github.com/tauri-apps/binary-releases` 下载 NSIS 3.11，本机网络下连接超时（WiX 源可达）。
  网络通畅时把 `tauri.conf.json` 的 `targets` 改回 `["msi", "nsis"]` 即可。
  另注：首次 `npm run build` 在本机约 **1 小时**（Celeron N5095 + LTO），后续增量构建仅数分钟。

### 环境要求（桌面端）
- Rust ≥ 1.77（实测 1.98.1）+ VS2022 BuildTools（VCTools workload）+ Windows 10/11 SDK。
- Windows 用户每次开 shell：`source apps/desktop/dev-env.sh`。

### Planned
- 文档站（VitePress 在线阅读）。
- P4 开源发布（README 落地页打磨 + Show HN）。

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
