# MiniYuxi 桌面端接入说明（P3）

> 对应 [`三端统一架构与开源增长方案.md` §3](三端统一架构与开源增长方案.md)。
> **一句话设计原则**：外壳只做窗口，内核只写一次。

---

## 1. 总览：六层对齐

```
Desktop UI (apps/desktop/src 启动壳)
   ↓ IPC（status / restart / open_data_dir 三个窄命令）
Main Process (apps/desktop/src-tauri/src/lib.rs · 窗口 · sidecar 生死)
   ↓ localhost
Local App Server (= api.py，Python 内核常驻；run.py --sidecar)
   ↓
Session Runtime (会话常驻 / 恢复 / 重连)
   ↓
Agent Loop (core/agent_loop)
   ├→ Tools Registry · Memory · RAG · Skills · Guard · Audit
```

---

## 2. 通信契约（外壳 ↔ 内核）

### 2.1 sidecar → 外壳：READY 契约

```text
MINIYUXI_SIDECAR_READY {"ok":true,"host":"127.0.0.1","port":8801,"url":"http://127.0.0.1:8801",
                        "token":"<jwt>","tenant":"default","user":"admin","role":"admin",
                        "pid":1234,"version":"0.2.0"}
```

| 通道 | 用途 | 兜底 |
|---|---|---|
| `stdout` 一行 | 主通道；Tauri 侧 grep 前缀解析 | `data/sidecar.json`（sidecar 一启动就写） |
| `POST /api/desktop/shutdown` | 外壳退出时优雅停机（→ server.should_exit） | 400ms 超时后 `child.kill()` |

### 2.2 外壳 → 前端：Tauri events

| 事件 | payload | 用途 |
|---|---|---|
| `sidecar://status` | `{url, port}` 或 `{phase, kind}` | 启动壳阶段文案 |
| `sidecar://log` | `{line}` | 把内核 stdout/stderr 流到前端日志面板 |
| `sidecar://exit` | `{code, signal}` | 内核挂了 → 启动壳显红色错误 |

### 2.3 token 注入

`WebviewWindowBuilder::initialization_script` 在工作台页面任何 JS 之前执行：

```js
localStorage.setItem('miniyuxi_token', <token>);
localStorage.setItem('miniyuxi_role',   <role>);
localStorage.setItem('miniyuxi_tenant', <tenant>);
window.__MINIYUXI_DESKTOP__ = true;
```

> **Web 端 0 改动**：看到的界面就是仓库根 `web/index.html` 那份，
> `wb_workbench.js` 第 23 行直接读 `localStorage.getItem('miniyuxi_token')`。

---

## 3. 三条跑通路径

### 3.1 离线贯通（不装 Rust / Node 也能验证）

```bash
python examples/desktop_tour/code.py
```

7 步通过 = 「外壳→sidecar→api.py→core/」全链路打通。下一步只是把外壳换成 Tauri。

### 3.2 开发模式

设两个环境变量跳过打包步骤，直接用系统 Python 跑 `run.py --sidecar`：

```powershell
$env:MINIYUXI_SIDECAR_PY = "E:\HR有关AI\AI应用基座最佳实践\14_自研MiniYuxi\run.py"
$env:MINIYUXI_PYTHON    = "C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
$env:MINIYUXI_PORT      = "8801"   # 可选

cd apps/desktop
npm install        # 首次安装 @tauri-apps/cli；其他代码零原生依赖
npm run dev        # 自动 cd src-tauri && cargo run
```

**热重启内核**：窗口里有「重启内核」按钮 → 走 `restart_sidecar` 命令 →
Rust 端先 POST `/api/desktop/shutdown`，再 `spawn_sidecar` 重新拉起。

### 3.3 生产打包

```bash
cd apps/desktop
npm run sidecar    # → apps/desktop/src-tauri/binaries/miniyuxi-sidecar-<HOST_TRIPLE>.exe
npm run build      # → src-tauri/target/release/bundle/{msi,nsis}/MiniYuxi_0.2.0_x64-*.msi
```

> macOS / Linux 上同样的 `npm run sidecar` 会打 `miniyuxi-sidecar-aarch64-apple-darwin`
> 等文件名；`npm run build` 出 `.dmg` / `.AppImage`。
> Tauri 的 `externalBin` 会按当前 host 平台自动挑选对应 triple 的 sidecar。
>
> ⚠️ **命名规则（cargo 实测校准）**：externalBin 条目是前缀、target triple 是**后缀**，
> 即 `miniyuxi-sidecar-x86_64-pc-windows-msvc.exe`。写反成 `<triple>-<name>` 会报
> ``resource path `binaries\xxx` doesn't exist``。`scripts/build_sidecar.py` 已按正确规则生成。

---

## 4. 关键文件索引

| 文件 | 作用 |
|---|---|
| `run.py --sidecar` | sidecar 主进程；签发桌面 token + READY 契约 + stdion 看门狗 + 优雅退出 |
| `core/auth.make_token(..., ttl=...)` | 桌面 token 默认 7 天（`MINIYUXI_SIDECAR_TOKEN_TTL_H` 覆盖） |
| `core/config.DATA_DIR` | 受 `MINIYUXI_DATA_DIR` 控制；冻结时 `run.py::_frozen_bootstrap` 自动落 `%LOCALAPPDATA%/MiniYuxi/data` |
| `api.py /api/desktop/shutdown` | 外壳退出前调一次；权限 `tenant.manage`（仅管理员） |
| `apps/desktop/src/index.html` | 启动壳（内核起来后即被替换） |
| `apps/desktop/src-tauri/src/lib.rs` | sidecar 生命周期 + 窗口导航 + 优雅停机 |
| `apps/desktop/src-tauri/capabilities/default.json` | 权限收口：只允许拉起 `binaries/miniyuxi-sidecar` |
| `apps/desktop/src-tauri/tauri.conf.json` | `externalBin` / 窗口 / `withGlobalTauri` |
| `scripts/build_sidecar.py` | PyInstaller 打 sidecar（自动识别 host target triple） |
| `examples/desktop_tour/code.py` | 离线贯通演示（核心验收用例） |
| `tests/test_desktop_sidecar.py` | 单元（ttl 生效）+ 端到端（tour 全绿）自检 |

---

## 5. 风险与边界

| 风险 | 等级 | 说明 / 缓解 |
|---|---|---|
| 首启慢（~5s） | 🟡 | sidecar 启动钩子跑每日备份 + 合同预警。生产可拆后台线程，探针到 200 即 READY。 |
| desktop token 7 天 TTL 偏长 | 🟡 | 该 token 只对回环 sidecar 本进程有效；超时后浏览器跳登录页重登即可。`MINIYUXI_SIDECAR_TOKEN_TTL_H` 可调。 |
| 打包后路径 | 🟢 | 冻结态 `BASE_DIR` 变临时 `_MEIPASS`；`run.py::_frozen_bootstrap` 已把 `DATA_DIR` 重定向到 `%LOCALAPPDATA%/MiniYuxi/data`。 |
| 退出留孤儿进程 | 🟢 | 双保险 —— `POST /api/desktop/shutdown`（优雅）+ `child.kill()`（400ms 后兜底）；Tauri `RunEvent::Exit` 钩子触发。 |
| 侧通道 stdin EOF 误退出 | 🟢 | 默认禁用；`MINIYUXI_SIDECAR_WATCH_STDIN=1` 才启用（外层被强杀时管道关闭 → sidecar 自退）。 |
| macOS `.icns` 图标 | 🟢 | Pillow 已生成（如缺，跑 `npm install && npx @tauri-apps/cli icon` 一键补齐）。 |

---

## 6. 验收清单（提交前跑一遍）

- [ ] `python tests/test_desktop_sidecar.py`  → 2/2 通过
- [ ] `python examples/desktop_tour/code.py` → 7/7 步通过，exit=0（源码内核）
- [ ] `python examples/desktop_tour/code.py --exe apps/desktop/src-tauri/binaries/miniyuxi-sidecar-<triple>.exe`
      → 7/7 步通过（**冻结内核同样遵守 READY 契约**，这一步能提前发现 PyInstaller 漏打模块/漏带 `web/`）
- [ ] `python tests/selftest.py`              → 20/20 通过（保证 sidecar 改动没误伤内核）
- [ ] `cd apps/desktop && npm install && npm run dev` → 启动壳正常显示"内核就绪…"，工作台窗口弹出