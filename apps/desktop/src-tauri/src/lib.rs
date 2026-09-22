//! MiniYuxi 桌面端外壳（P3）
//!
//! 职责边界（对应 docs/三端统一架构与开源增长方案.md §3.2 六层）：
//!   Desktop UI (Tauri webview)  ← 本文件 + ../src 启动壳
//!     ↓ Preload/IPC（窄桥：只有 status / restart / open_data_dir 三个命令）
//!   Main Process（窗口 · 生命周期 · sidecar 生死）  ← 本文件
//!     ↓ localhost
//!   Local App Server（api.py，Python 内核常驻）
//!     ↓
//!   core/（Agent Loop · 工具 · 记忆 · RAG · 技能 · 审计）
//!
//! 外壳**不实现任何业务逻辑**：内核就绪后直接把窗口导航到 http://127.0.0.1:<port>，
//! 看到的界面与 Web 端是同一份 web/index.html —— 内核只写一次，三端永远一致。

use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent, TerminatedPayload};
use tauri_plugin_shell::ShellExt;
use url::Url;

/// tauri.conf.json 中 bundle.externalBin 的条目名（打包后的 Python 内核可执行文件名）
const SIDECAR_NAME: &str = "binaries/miniyuxi-sidecar";
/// run.py --sidecar 打印的就绪契约行前缀（另一条兜底通道是 data/sidecar.json）
const READY_PREFIX: &str = "MINIYUXI_SIDECAR_READY ";
const SPLASH_LABEL: &str = "splash";
const WORKBENCH_LABEL: &str = "workbench";

/// 与 run.py 中 MINIYUXI_SIDECAR_READY 的 JSON 完全对应
#[derive(Clone, Debug, Serialize, Deserialize)]
struct SidecarInfo {
    ok: bool,
    host: String,
    port: u16,
    url: String,
    token: String,
    tenant: String,
    user: String,
    role: String,
    pid: u32,
    version: String,
}

#[derive(Default)]
struct SidecarState {
    info: Arc<Mutex<Option<SidecarInfo>>>,
    child: Arc<Mutex<Option<CommandChild>>>,
}

/// 拉起 Python 内核 sidecar 并接管它的 stdout/stderr/生命周期。
fn spawn_sidecar(app: &tauri::AppHandle, state: &SidecarState) -> Result<(), String> {
    let mut args: Vec<String> = vec!["--sidecar".into()];
    if let Ok(p) = std::env::var("MINIYUXI_PORT") {
        if p.parse::<u16>().is_ok() {
            args.push("--port".into());
            args.push(p);
        }
    }

    // 两条启动路径：
    //  1) 打包态：用 externalBin 里的 miniyuxi-sidecar 可执行文件；
    //  2) 开发态：设了 MINIYUXI_SIDECAR_PY（run.py 路径）时，用系统 python 直接跑源码，
    //     省掉每次改内核都重新打 PyInstaller 包。
    let (mut rx, child) = match std::env::var("MINIYUXI_SIDECAR_PY") {
        Ok(script) => {
            let py = std::env::var("MINIYUXI_PYTHON").unwrap_or_else(|_| {
                if cfg!(windows) { "python".into() } else { "python3".into() }
            });
            let mut a = vec![script];
            a.extend(args.iter().cloned());
            app.shell().command(py).args(a).spawn().map_err(|e| e.to_string())?
        }
        Err(_) => app
            .shell()
            .sidecar(SIDECAR_NAME)
            .map_err(|e| format!("找不到 sidecar 可执行文件 {SIDECAR_NAME}：{e}"))?
            .args(args)
            .spawn()
            .map_err(|e| format!("sidecar 启动失败：{e}"))?,
    };

    *state.child.lock().unwrap() = Some(child);

    let handle = app.clone();
    let slot = Arc::clone(&state.info);
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    if let Some(json) = line.trim().strip_prefix(READY_PREFIX) {
                        match serde_json::from_str::<SidecarInfo>(json) {
                            Ok(info) => {
                                *slot.lock().unwrap() = Some(info.clone());
                                let _ = handle.emit(
                                    "sidecar://status",
                                    serde_json::json!({ "url": info.url, "port": info.port }),
                                );
                                if let Err(e) = open_workbench(&handle, &info) {
                                    let _ = handle.emit(
                                        "sidecar://status",
                                        serde_json::json!({ "phase": format!("打开工作台失败：{e}"), "kind": "err" }),
                                    );
                                }
                            }
                            Err(e) => {
                                let _ = handle.emit(
                                    "sidecar://log",
                                    serde_json::json!({ "line": format!("READY 行解析失败：{e}") }),
                                );
                            }
                        }
                    } else {
                        let _ = handle.emit("sidecar://log", serde_json::json!({ "line": line }));
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    let _ = handle.emit("sidecar://log", serde_json::json!({ "line": line }));
                }
                CommandEvent::Error(msg) => {
                    let _ = handle.emit("sidecar://log", serde_json::json!({ "line": format!("[error] {msg}") }));
                }
                CommandEvent::Terminated(TerminatedPayload { code, signal, .. }) => {
                    let _ = handle.emit("sidecar://exit", serde_json::json!({ "code": code, "signal": signal }));
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// 内核就绪 → 新建工作台窗口（external URL + 注入 token）→ 关掉启动壳。
fn open_workbench(app: &tauri::AppHandle, info: &SidecarInfo) -> Result<(), String> {
    if app.get_webview_window(WORKBENCH_LABEL).is_some() {
        return Ok(());   // 已打开（例如手动重启内核后）就复用
    }
    let url = Url::parse(&format!("{}/", info.url)).map_err(|e| e.to_string())?;
    // token 注入：initialization_script 在目标页面任何脚本之前执行，
    // 等价于「这台电脑上已经登录」，Web 端那份 wb_workbench.js 无需任何改动。
    let inject = format!(
        "try{{localStorage.setItem('miniyuxi_token',{token});\
         localStorage.setItem('miniyuxi_role',{role});\
         localStorage.setItem('miniyuxi_tenant',{tenant});\
         window.__MINIYUXI_DESKTOP__=true;}}catch(e){{}}",
        token = serde_json::json!(info.token),
        role = serde_json::json!(info.role),
        tenant = serde_json::json!(info.tenant),
    );

    let win = WebviewWindowBuilder::new(app, WORKBENCH_LABEL, WebviewUrl::External(url))
        .title("MiniYuxi")
        .inner_size(1440.0, 900.0)
        .min_inner_size(1024.0, 680.0)
        .initialization_script(&inject)
        .build()
        .map_err(|e| e.to_string())?;
    win.show().map_err(|e| e.to_string())?;

    if let Some(splash) = app.get_webview_window(SPLASH_LABEL) {
        let _ = splash.close();
    }
    Ok(())
}

/// 用裸 TCP 发一次 POST /api/desktop/shutdown（避免为了一个请求引入 HTTP 客户端依赖）。
fn post_shutdown(info: &SidecarInfo) {
    let body = "{}";
    let req = format!(
        "POST /api/desktop/shutdown HTTP/1.1\r\n\
         Host: {host}:{port}\r\n\
         Authorization: Bearer {token}\r\n\
         Content-Type: application/json\r\n\
         Content-Length: {len}\r\n\
         Connection: close\r\n\r\n{body}",
        host = info.host, port = info.port, token = info.token, len = body.len()
    );
    if let Ok(mut stream) = TcpStream::connect((info.host.as_str(), info.port)) {
        let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
        let _ = stream.write_all(req.as_bytes());
        let mut buf = [0u8; 256];
        let _ = stream.read(&mut buf);
    }
}

/// 先礼后兵：请求内核优雅退出（不留孤儿进程），超时/失败再 kill。
fn stop_sidecar(state: &SidecarState) {
    if let Some(info) = state.info.lock().unwrap().clone() {
        post_shutdown(&info);
    }
    std::thread::sleep(Duration::from_millis(400));
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
    *state.info.lock().unwrap() = None;
}

// ─────────────────────── IPC：启动壳能用的三个窄命令 ───────────────────────

#[tauri::command]
fn sidecar_status(state: tauri::State<'_, SidecarState>) -> Option<SidecarInfo> {
    state.info.lock().unwrap().clone()
}

#[tauri::command]
fn restart_sidecar(app: tauri::AppHandle, state: tauri::State<'_, SidecarState>) -> Result<(), String> {
    stop_sidecar(&state);
    spawn_sidecar(&app, &state)
}

#[tauri::command]
fn open_data_dir() -> Result<String, String> {
    let dir = std::env::var("MINIYUXI_DATA_DIR").unwrap_or_else(|_| "data".to_string());
    #[cfg(target_os = "windows")]
    let _ = std::process::Command::new("explorer").arg(&dir).spawn();
    #[cfg(target_os = "macos")]
    let _ = std::process::Command::new("open").arg(&dir).spawn();
    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    let _ = std::process::Command::new("xdg-open").arg(&dir).spawn();
    Ok(dir)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![sidecar_status, restart_sidecar, open_data_dir])
        .setup(|app| {
            let handle = app.handle().clone();
            let state = handle.state::<SidecarState>();
            if let Err(e) = spawn_sidecar(&handle, &state) {
                let _ = handle.emit(
                    "sidecar://status",
                    serde_json::json!({ "phase": format!("内核启动失败：{e}"), "kind": "err" }),
                );
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("构建 MiniYuxi 桌面应用失败");

    app.run(|app_handle, event| {
        // 关窗/退出时务必带走 sidecar：否则 Python 内核会变成孤儿进程常驻后台
        if let RunEvent::Exit = event {
            let state = app_handle.state::<SidecarState>();
            stop_sidecar(&state);
        }
    });
}
