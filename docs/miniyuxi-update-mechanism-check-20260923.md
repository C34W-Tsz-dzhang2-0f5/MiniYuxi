# MiniYuxi 桌面版更新机制核查报告

- 核查日：2026-09-23（同时覆盖你提到的 2026-09-24 口径）
- 核查范围：桌面端更新机制 + 是否于核查日发布了新版本

## 结论（结论先行）

1. **更新机制：不存在自动更新，纯手工 MSI 分发。**
   Tauri 的 updater 插件完全未启用，应用不会自检、不会自升级；要发新版只能重新 `tauri build` 后手动分发安装包（README 下载入口 / 网盘），没有任何自动推送通道。

2. **核查日（09-23，含 09-24 口径）未发布任何新版本。**
   无 09-23 / 09-24 的 git commit、无 tag、版本号零变更、无新 MSI 产物。工作区虽有本会话的改动，但均未提交、未打版本、未重新打包。

## 一、更新机制明细（证据）

| 检查项 | 位置 | 现状 | 结论 |
|---|---|---|---|
| Tauri updater 插件 | `apps/desktop/src-tauri/tauri.conf.json` | 无 `plugins.updater` / `updater.endpoints` / `pubkey` | 未启用自动更新 |
| updater 依赖 | `apps/desktop/src-tauri/Cargo.toml` | 仅 `tauri` + `tauri-plugin-shell`，无 `tauri-plugin-updater` | 未启用 |
| 桌面运行权限 | `apps/desktop/src-tauri/capabilities/default.json` | 仅 `shell:allow-execute(sidecar)` + `shell:allow-kill` + core events | 无更新相关权限 |
| 桌面端自检逻辑 | `apps/desktop/src/*.js` | 无 `checkUpdate` / `updater` 引用 | 无自检 / 无提示升级 |
| 分发目标 | `tauri.conf.json` → `bundle.targets` | `["msi"]` | 仅 MSI 手工分发 |
| 内核版本契约 | `run.py` → `SIDECAR_VERSION = "0.2.0"` | 注释要求「与 pyproject.toml 保持一致」 | 硬编码，需手动同步 |

> 说明：桌面外壳启动内核走 `shell:allow-execute` 拉起自有 sidecar（Python 内核），与「更新」是两回事；当前没有任何从远端拉取新安装包的链路。

## 二、版本号现状（全部停留在未变更的 0.2.0）

| 版本源 | 版本号 | 最后修改时间 |
|---|---|---|
| `pyproject.toml` | 0.2.0 | 2026-09-22 11:29 |
| `apps/desktop/package.json` | 0.2.0 | 2026-09-22 11:56 |
| `apps/desktop/src-tauri/Cargo.toml` | 0.2.0 | 2026-09-22 12:03 |
| `apps/desktop/src-tauri/tauri.conf.json` | 0.2.0 | 2026-09-22 16:55 |
| `run.py` → `SIDECAR_VERSION` | 0.2.0 | 2026-09-22 12:00 |
| 本地已出 MSI 产物 | `MiniYuxi_0.2.0_x64_en-US.msi` | 2026-09-22 16:39 |

## ⚠️ 风险分级

### 🔴 高 — 版本号漂移（changelog 超前实际版本两个 minor）
`CHANGELOG.md` 已记录到 `[0.2.2] - 2026-09-22`（含桌面端 P3 落地、CLI P2 等），**但所有版本源与已出 MSI 仍是 0.2.0**。即 changelog 比真实版本「超前两档」。

- **敞口**：若今天要「发新版」，实际是**第一次把版本号对齐到真实功能**。客户 / 同事若按 changelog 认为已装 0.2.2，会与 MSI 文件名 0.2.0、内核 `health` 返回的 `version: 0.2.0` 对不上，造成支持与合规混乱。
- **处置（发版前必做）**：先把五处版本源 + `SIDECAR_VERSION` + 重新 build 的 MSI 文件名统一 bump 到同一目标号（如 0.2.3），再 `tauri build`，并补 `git tag`。

### 🟢 低 — 无自动更新本身（非缺陷，但是产品决策）
本地优先 / 数据不出本机是 MiniYuxi 的定位，不接 Tauri 自动更新符合「内网 / 离线可用」诉求。仅需注意：发版完全依赖人工，要有人负责重打包 + 替换下载入口。

## 三、核查日工作区变更（≠ 发布）
`git status` 显示存在未提交改动：`api.py / core/db.py / core/rag.py / core/subagent.py / scripts/build_sidecar.py / web/*` 等已修改，以及一批未跟踪的 `docs/scenes`、`docs/desktop-*` 报告文件。

- 这些改动即本会话所做的 **ZCode 逆向第一波 + 第二波 P1**（Command / 子智能体 / 知识库检索可点击引用等）。
- 它们**尚未 commit、未打版本、未产生新 MSI**，不构成发布。

## 四、建议的发版动作清单（若决定近期发布）
1. 统一版本号到目标号（五处源 + `SIDECAR_VERSION` + 重新 build 的 MSI 名）— 消除 🔴 漂移。
2. `python scripts/verify.py`（或 `--quick`）跑质量闸门。
3. `tauri build` 产出新 MSI（本机约 1 小时，Celeron N5095 + LTO；后续增量仅数分钟）。
4. 补 `git tag vX.Y.Z` + 把 CHANGELOG 的 `[Unreleased]` 收口为 `[X.Y.Z] - 日期`。
5. 手动替换 README 下载入口 / 网盘链接（无自动推送，必须人手处理）。
