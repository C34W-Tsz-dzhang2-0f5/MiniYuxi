# MiniYuxi Desktop

> Tauri 外壳 + Python 内核作 **sidecar 常驻** —— 三端统一架构下的桌面端实现
> （方案见 [`docs/三端统一架构与开源增长方案.md` §3](../../docs/三端统一架构与开源增长方案.md)）。

```
Desktop UI (../src, 启动壳)
   ↓ IPC（status / restart / open_data_dir）
Main Process (src/lib.rs：sidecar 生命周期 · 窗口 · token 注入)
   ↓ localhost
Local App Server (= 现有 api.py，Python 内核常驻)
   ↓
core/（Agent Loop · 工具 · 记忆 · RAG · 技能 · 审计）
```

**核心原则**：外壳只做「窗口 + sidecar 生死」。内核就绪后直接 `WebviewUrl::External(url)`
导航到本地 http，**看到的界面就是 `web/index.html` 那一份**，业务逻辑零重复。

## 目录

| 路径 | 作用 |
|---|---|
| `src/` | 启动壳（无构建步骤，纯 HTML/CSS/JS）。内核起来后即被替换 |
| `src-tauri/src/lib.rs` | 主进程：拉起 sidecar → 解析 READY → 注入 token → 打开工作台 → 退出时带走 |
| `src-tauri/src/main.rs` | 入口；release 隐藏控制台窗口 |
| `src-tauri/Cargo.toml` | 仅 4 个依赖：`tauri` / `tauri-plugin-shell` / `serde_json` / `url` |
| `src-tauri/tauri.conf.json` | 窗口 / 打包 / `externalBin`（miniyuxi-sidecar） |
| `src-tauri/capabilities/default.json` | 权限收口：**只允许拉起自己的 sidecar**，不给任意命令执行 |
| `src-tauri/icons/` | 应用图标（运行时用 Pillow 现成生成；改色后重跑 `scripts/gen_desktop_icons.py`） |
| `src-tauri/binaries/` | **打包后的 Python sidecar 可执行文件**（不提交，`.gitignore` 已排除） |

## 跑通路线

### ⓪ Windows 环境准备（只需一次）

```powershell
# 1) Rust（免管理员，装到 %USERPROFILE%\.cargo）
winget install Rustlang.Rustup
rustup default stable-x86_64-pc-windows-msvc      # 装完必补：否则 "no active toolchain"

# 2) MSVC 生成工具 + Windows SDK（Tauri 链接必需，约 8GB、需管理员）
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact `
  --accept-source-agreements --accept-package-agreements `
  --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

装完每次开 shell 前先 `source apps/desktop/dev-env.sh`（自动探测 MSVC / SDK 版本，设好 PATH / LIB / INCLUDE）。

> **三个必踩的坑**（本机实测，已写进 `dev-env.sh` / 注释）：
> 1. `winget` 装 VS 报 **退出码 5002** —— 真因不是权限，是环境里 `HTTP_PROXY` 与 `http_proxy` 大小写两份并存，
>    .NET 用不区分大小写字典收集环境变量时抛「已添加项」，setup 压根没启动。
>    解法：`env -u http_proxy -u https_proxy -u all_proxy -u no_proxy` 后再跑安装器。
> 2. **`link` 撞名** —— Git Bash 自带 GNU `link.exe`（建硬链接）抢在 MSVC 链接器前，rustc 报 `link: extra operand '*.rcgu.o'`。
>    解法：MSVC bin 提到 PATH 最前（bash 认 `/c/...`、Windows 认 `C:/...`，两种都塞）。
> 3. **LNK1181 找不到 kernel32.lib** —— 缺 LIB/INCLUDE，补 MSVC `lib/x64` + SDK `Lib/<ver>/{ucrt,um}/x64`。
>
> 另：`vcvars64.bat` 这条路在本工作台走不通（Bash 安全策略禁止 `cmd.exe`），所以用 `dev-env.sh` 手工拼等价环境。

### ① 离线贯通（不装 Rust / Node）

```bash
# 仓库根目录
python examples/desktop_tour/code.py
```

7 步通过 = 「桌面六层」链路在 Python 内核层完全跑通。下一步只是把外壳换成 Tauri。

### ② 开发模式（外壳跑起来，内核走源码）

设两个环境变量跳过打包步骤，直接用系统 Python 跑 `run.py --sidecar`：

```powershell
$env:MINIYUXI_SIDECAR_PY = "E:\HR有关AI\AI应用基座最佳实践\14_自研MiniYuxi\run.py"
$env:MINIYUXI_PYTHON     = "C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
# 可选：固定端口便于联调
$env:MINIYUXI_PORT       = "8801"

cd apps/desktop
npm install            # 首次安装 @tauri-apps/cli（其它代码零原生依赖）
npm run dev            # 自动 cd src-tauri && cargo run
```

> 改内核（`core/`、`api.py`、`run.py`）无需重打 sidecar，**热重启即可**（窗口里有「重启内核」按钮）。

### ③ 生产打包

```bash
# 1. 先打 Python sidecar 单一可执行文件（→ src-tauri/binaries/）
cd apps/desktop
npm run sidecar
# 或：python ../../scripts/build_sidecar.py

# 2. 再打 Tauri 安装包（→ src-tauri/target/release/bundle/msi/MiniYuxi_0.2.0_x64_en-US.msi）
npm run build
```

macOS / Linux 上同样的 `npm run sidecar` 会打 `binaries/miniyuxi-sidecar`（无后缀），
再 `npm run build` 出 `.dmg` / `.AppImage`。

> **为什么 Windows 只留 `msi`**：Tauri 的 `nsis` 目标要从
> `github.com/tauri-apps/binary-releases` 下 NSIS 3.11，本机网络下该地址**连接超时**
> （WiX 那个源反而通）。已把 `tauri.conf.json` 的 `targets` 收成 `["msi"]`；
> 网络通畅的机器上想出 NSIS 安装包，改回 `["msi", "nsis"]` 即可。
> 首次 `npm run build` 约 **1 小时**（Celeron N5095 + LTO），之后增量构建只要几分钟。

## 通信契约（外壳 ↔ 内核）

```text
MINIYUXI_SIDECAR_READY {"ok":true,"host":"127.0.0.1","port":8801,"url":"http://127.0.0.1:8801",
                        "token":"<jwt>","tenant":"default","user":"admin","role":"admin",
                        "pid":1234,"version":"0.2.0"}
```

| 通道 | 用途 | 出错回退 |
|---|---|---|
| `stdout` 一行 | 主通道；外壳 grep 前缀解析 | `data/sidecar.json`（sidecar 一启动就写） |
| `POST /api/desktop/shutdown` | 外壳退出时优雅停机 | 400ms 超时后 `child.kill()` |
| `sidecar://status` / `sidecar://log` / `sidecar://exit` 事件 | Tauri → 前端启动壳 | — |

## 已知边界 & 下一步

- 🟡 **首启慢（~5s）**：sidecar 启动钩子跑每日备份 + 合同预警。生产可拆后台线程，预启动至 200 后再 READY。
- 🟡 **desktop token TTL 默认 7 天**（`MINIYUXI_SIDECAR_TOKEN_TTL_H` 覆盖）：
  该 token 只对回环 sidecar 本进程有效；超时后浏览器跳登录页重登即可。
- 🟢 **不依赖 Docker / Node 服务进程**：本机硬约束已满足（见 G2）。
- 🟢 **零重复业务代码**：外壳 JS 只 50 行；Rust 端不调 `core/`，只读 stdout + 发 HTTP。