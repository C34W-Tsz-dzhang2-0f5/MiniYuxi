# 更新日志 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/) 约定，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（暂无）

## [0.4.0] - 2026-09-24

> 定位更正为「企业级 Agent」后，本版落地其**最直接的工程后果**：
> 数据可以出本机，但出境必须**可按数据分级配置**、且**可审计**——不是全开/全关。

### Added
- **数据出境管控 `core/egress.py`（企业级定位落地）**
  - **出境闸门 `guard()`**：唯一收口点。5 类目的地 × **10 个真实出口全部过闸**：
    `llm`（gateway / model_hub / provider_router）、`embedding`（rag.embed / rebuild_vectors）、
    `search`（tools_registry.web_search）、`external_rag`（rag_adapter）、
    `connector`（connectors.send_message）。
  - **三态模式**：`allow` / `deny` / `approval`（approval 复用既有 HITL 审批卡，不另起一套）。
  - **数据分级**：自动分级 `classify()`（HR·商业敏感关键词 + 身份证/银行卡/手机号/邮箱格式识别）
    → `public` / `internal` / `confidential`；策略可按级差异化配置。
  - **策略优先级**：`lockdown` > 环境变量 `MINIYUXI_EGRESS_<CLASS>` > `by_level` > `default` > 内置 allow。
  - **姿态预设**：`balanced`（默认全放行）/ `strict`（机密级出境需审批）/ `lockdown`（全禁）。
  - **出境日志**：`egress_log` 表 + 同时写入 SOC 哈希链（`action=egress.*`），
    **被拒绝的出境同样留痕**；只记目的地主机 / 字节数 / 脱敏截断摘要，**绝不记载荷全文**
    （否则日志本身成为新的泄露面）。
  - **API**：`/api/egress/{inventory,policy,preset,log,classify}`（读 `chat`/`audit.read`，写 `tenant.manage`）。
  - **默认全放行**：定位是「数据可以出本机」，开箱即禁会让产品直接不可用；
    企业侧按需收紧，或 `MINIYUXI_EGRESS_LOCKDOWN=1` 一键全禁。
  - guard 自身异常默认 **fail-open**（不让审计组件变成单点故障），
    可用 `MINIYUXI_EGRESS_FAIL_MODE=closed` 改为 fail-closed。

### Fixed
- **`run.py` 跨盘符启动崩溃**：`MINIYUXI_DATA_DIR` 指向与项目不同盘符（如 `D:\`）时，
  `os.path.relpath()` 抛 `ValueError: path is on mount 'C:', start on mount 'E:'`；
  且 `ValueError` **不是 `OSError`**，会穿透 `except OSError` 直接干掉启动。已降级为显示绝对路径。
- **`egress.classify()` 漏判**：原关键词表只有「辞退/解雇」，漏了更常用的「解除劳动合同」，
  导致「关于解除劳动合同的通知」被判成 `internal`（**漏判 = 敏感数据无保护出境**）。已补齐
  解除劳动合同 / 经济补偿 / 调岗 / 降薪 / 劝退 / 员工档案 等。

### Changed
- 版本号 0.3.0 → **0.4.0**（新增功能，minor 位）。

### Verified
- `tests/_verify_egress.py`：**56/56** —— 含端到端证明「策略拒绝时 `requests.post` 一次都没被调用」，
  以及五类目的地出口逐一验证（每类都断言零发包 + 正确降级）。
- `tests/_verify_egress_api.py`：**27/27** —— 起真实服务走真实 HTTP，含 RBAC 越权拒绝（viewer 403）。
- `tests/selftest.py`：**20/20** —— 零回归。
- `scripts/check_version_consistency.py`、`scripts/audit_licenses.py`：通过。

## [0.3.0] - 2026-09-24

> 本版新增两条**基础设施层**能力（univer 办公操作面、本地工具市场），按 SemVer 为 minor 升级。
> 同时更正产品定位为「**企业级 Agent · 数据可以出本机 · 零 Docker · 可商用**」，
> 并修掉一个隐蔽的公式引擎缺陷与长期存在的版本号漂移。

### Added
- **univer 办公操作面（P0）**：内嵌开源 Office SDK（Apache-2.0），Agent 可产出**可编辑**的表格/文档，
  补上此前「HR 只能产出纯文本」的缺口。
  - 离线打包：`tools/office-bundle/`（esbuild IIFE）→ `web/vendor/univer/univer.bundle.js`（12.0 MB）
    + `univer.bundle.css`（116 KB）。**无 CDN 回退**，资产缺失时返回 503 + 构建指引。
  - 后端：`core/office.py`（`office_docs` 表，租户隔离）+ `GET/POST/DELETE /api/office/*`。
  - 前端：`web/office/office-host.js`（懒加载、全屏 overlay、表格/文档切换、存档 CRUD）+ 明暗双主题 CSS；
    顶部导航新增「办公套件」入口。
- **本地工具市场（P1，treg 理念本地化）**：把「统一工具目录」理念落到本机——
  `tools_registry` 增加 `category/tags/risk/source/requires_approval/updated_at` 元数据，
  新增 `GET /api/market/list`、`GET /api/market/{name}`、`POST /api/market/{name}/toggle`（写审计），
  前端新增「工具市场」抽屉（分类标签条 + 工具卡片 + 启停开关）。
  **不接第三方工具代理服务、不注入远程凭据**——凭据与元数据全部留在本机。
- **`core/version.py`：版本号唯一来源（Single Source of Truth）**。
  此前 `api.py` 写死 `0.1.0`、`run.py`/`cli.py`/各清单写 `0.2.0`，对外报三个版本号。
  现在 Python 侧统一 `from core.version import __version__`。
- **`scripts/check_version_consistency.py`**：校验 `core/version.py` 与
  `pyproject.toml` / `tauri.conf.json` / `apps/desktop/package.json` / `Cargo.toml` / `CHANGELOG.md`
  是否一致（可进 CI，防再次漂移）。
- **`scripts/audit_licenses.py`：商用授权与数据外联审计**。扫描 `node_modules`（含传递依赖）列出授权分布、
  标出 copyleft/未知授权；扫描打包产物列出全部 URL 主机并对 telemetry/埋点类地址告警。exit 1 = 有问题。
  首次审计结论：`tools/office-bundle` 126 个真实包全部宽松授权（MIT/Apache-2.0/BSD/ISC/0BSD），
  产物 760 个 URL 无任何埋点地址。
- **`tests/_verify_office_formula.py`**：公式引擎回归测试（断言 Worker 被创建 + `=SUM(A1:A3)` 真返回数字）。
- **`scripts/verify.py`：一键质量闸门**（本地与 CI 同构）。
  §6 里点名的入口此前只有 bash 版 `scripts/verify-precommit.sh`，Windows 跑不顺；现在一条命令
  `python scripts/verify.py` 复现 CI 的全部卡点，支持 `--quick`（只跑纯 stdlib）/ `--json`（机器可读）。
- CI 新增 **Desktop sidecar 单元测试**步骤（`--unit-only`）。此前 P3 新增的 `tests/test_desktop_sidecar.py`
  没进 CI 是个缺口；端到端 tour 依赖 PyInstaller 产物（Windows 专属），故只挂跨平台确定的单元部分。

### Fixed
- **公式引擎不计算（SUM/AVG 填了不出结果）**。根因是 `@univerjs/preset-sheets-core` 的 preset 工厂里
  `notExecuteFormula: !!workerURL` —— **主线程没传 `workerURL` 时公式执行被显式关掉**（无报错、无告警）。
  修法：新增 worker 入口 `tools/office-bundle/src/office-worker-entry.js` 并产出 `univer.worker.js`（8.9 MB），
  `api.py` 加 `/vendor/univer/univer.worker.js` 路由，前端传 `workerURL`。
- **版本号三源漂移**：`/api/health` 曾报 `0.1.0` 而 `run.py`/`pyproject.toml` 报 `0.2.0`。
  已统一到 `core/version.py`（见 Added）。
- **`.gitignore` 漏掉 246 MB 构建产物**：`node_modules/`（207 MB）、`.npm-cache/`（26 MB）、
  `web/vendor/univer/`（13 MB）此前都会被提交。已补规则。
- `CHANGELOG.md` 0.2.2 条目把 Tauri `externalBin` 命名写成 `<HOST_TRIPLE>-miniyuxi-sidecar`（**写反**），
  与实现（`miniyuxi-sidecar-<triple>`，triple 作后缀）不符。文档写反比代码写错更坑人，已校准。
- `scripts/build_sidecar.py::host_target_triple` docstring 同样写成"前缀"，改为"后缀"。

### Changed
- **产品定位更正**：由「本地优先 · 数据不出本机」更正为「**企业级 Agent · 数据可以出本机 · 零 Docker · 可商用**」。
  据此重推 `docs/miniyuxi-fullstack-rebuild-20260924.md` 全文决策：
  - 三条把关轴替代原「数据不出本机」红线：**零 Docker（底座）/ 可商用（授权）/ 第三方权益**；
  - 放开云端 LLM/API、云端微调、云端浏览器智能体；
  - 出站白名单与 HITL 审批门保留，但理由由「合规阻断」改为「成本与风险管控 + 可审计」；
  - `pyproject.toml` 的 `description` 同步更正。
- `docs/三端统一架构与开源增长方案.md`：§6「发布前」三项打 ✅；§8 交付物清单去掉
  「README（待升级）」「.github（待建）」等过时标记，补 `README.md` / `readme_hero.png` /
  `.github` / `scripts/verify.py` 已交付行，并写明 P4 剩余为「发布日/持续」对外动作。

## [0.2.2] - 2026-09-22

### Added
- **桌面端（P3）落地**：Tauri 外壳 + Python 内核作 **sidecar 常驻**。
  - `run.py --sidecar`：强制回环 127.0.0.1、自动选空闲端口、`MINIYUXI_SIDECAR_READY {...}` 契约（stdout + `data/sidecar.json` 双通道）、`POST /api/desktop/shutdown` 优雅停机、可选 stdin 看门狗（`MINIYUXI_SIDECAR_WATCH_STDIN=1`）。
  - `core/auth.make_token(payload, ttl=...)`：桌面本地长会话 token（默认 7 天，受 `MINIYUXI_SIDECAR_TOKEN_TTL_H` 覆盖）。
  - `core/config.DATA_DIR` 受 `MINIYUXI_DATA_DIR` 控制；`run.py::_frozen_bootstrap` 在 PyInstaller 冻结时自动落 `%LOCALAPPDATA%/MiniYuxi/data`，避免 BASE_DIR 变 `_MEIPASS` 临时路径。
  - `cli.py serve --sidecar`（透传给 run.py）。
  - `apps/desktop/`：Tauri 外壳（`src/` 启动壳 + `src-tauri/` 主进程 4 依赖）、`withGlobalTauri` 走 `window.__TAURI__`、权限收口 `shell:allow-execute` 只允许自己的 sidecar；图标用 Pillow 现成生成（含 macOS `.icns`）。
  - `scripts/build_sidecar.py`：PyInstaller 打 `miniyuxi-sidecar-<target triple>` 到 `apps/desktop/src-tauri/binaries/`（Tauri externalBin 格式，triple 是**后缀**）。
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
