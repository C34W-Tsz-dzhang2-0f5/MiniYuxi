# 05 · 桌面装机版重出 MSI

Status: `ready-for-human`（打包动作，非纯代码；需阿长确认时机）
Depends on: 01–04 视纳入范围
Owner: —

## 目标
本会话及后续所有 core 改动**只在网页版即时生效**，桌面装机版必须**重出 MSI** 才能用上。目标：产出含最新修复的安装包，桌面版功能与网页版对齐。

## 步骤（既有流程，见项目记忆）
1. 冻结 sidecar：`scripts/build_sidecar.py`（PyInstaller）→ `miniyuxi-sidecar.exe`。
2. WiX v3.14 便携版打包（`C:\Users\Administrator\.workbuddy-ai\tools\wix314\`）。
3. **先卸旧再装**（ProductCode 不同、InstallLocation 同）→ 装 `C:\Program Files\MiniYuxi\`。
4. 装机版 sidecar 落盘校验：`lib.rs` `SIDECAR_NAMES` 裸名优先（`miniyuxi-sidecar.exe` 在根，不建 `binaries/`）。
5. 注册表核验版本：`HKLM\...\Uninstall\*` 的 `DisplayVersion`。
6. 冒烟：`C:\Users\Administrator\AppData\Local\MiniYuxi\data\miniyuxi.db`，登录 `admin/admin123`，跑主对话 + 装技能 + 写文件。

## 验收
- [ ] MSI 构建成功，版本号 = `core/version.py`。
- [ ] 装机后主对话可执行工具（含 01–04 纳入项）。
- [ ] 注册表 DisplayVersion 核验通过。

## Done
- artifact: _（构建后填）_
