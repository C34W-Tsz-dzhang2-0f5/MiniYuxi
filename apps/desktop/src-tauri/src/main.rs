// 打包/release 下隐藏 Windows 控制台窗口（内核日志走 sidecar stdout，不依赖控制台）
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    miniyuxi_desktop_lib::run()
}
