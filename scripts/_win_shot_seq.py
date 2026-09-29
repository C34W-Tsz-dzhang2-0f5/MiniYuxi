"""对 WorkBuddy 中文版窗口做「点击 + 截图」序列取证（阿长 2026-09-24 授权）。

设计原则：**可还原**。脚本按步骤点按并截图，最后一步点回原会话，把界面恢复到初始状态。
坐标一律用「窗口内相对坐标」，避免受窗口位置变化影响。

用法： python scripts/_win_shot_seq.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shcore = ctypes.windll.shcore

SW_RESTORE, SW_SHOW = 9, 5
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004

HWND = 132724          # WorkBuddy.exe "WorkBuddy"（中文版 5.6.2）
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "_shots" / "wb-live-20260924"


def set_dpi_aware() -> None:
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def rect_of(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def activate(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)
    fg = user32.GetForegroundWindow()
    tid_fg = user32.GetWindowThreadProcessId(fg, None)
    tid_me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(tid_fg, tid_me, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(tid_fg, tid_me, False)


def click_at(hwnd: int, rx: int, ry: int) -> None:
    """在窗口内相对坐标 (rx, ry) 处单击。"""
    x, y, _w, _h = rect_of(hwnd)
    sx, sy = x + rx, y + ry
    user32.SetCursorPos(sx, sy)
    time.sleep(0.25)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def shot(hwnd: int, name: str) -> None:
    from PIL import ImageGrab
    x, y, w, h = rect_of(hwnd)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / name
    img.save(p)
    print(f"  ✓ {name}  ({w}x{h})")


def main() -> int:
    set_dpi_aware()
    activate(HWND)
    time.sleep(1.6)

    print("① 初始态（对话态 + 完整左侧栏）")
    shot(HWND, "01-对话态-完整左侧栏.png")

    print("② 点「新建任务」→ 欢迎页")
    click_at(HWND, 65, 106)
    time.sleep(1.8)
    shot(HWND, "02-新建任务-欢迎页.png")

    print("③ 点模型名（Hy3）→ 模型下拉")
    click_at(HWND, 1013, 793)
    time.sleep(1.4)
    shot(HWND, "03-模型下拉.png")

    print("④ 按 Esc 关下拉")
    user32.keybd_event(0x1B, 0, 0, 0)          # VK_ESCAPE down
    time.sleep(0.05)
    user32.keybd_event(0x1B, 0, 2, 0)          # up
    time.sleep(0.8)

    print("⑤ 还原：点回原会话「HR有关AI」")
    click_at(HWND, 36, 687)
    time.sleep(1.6)
    shot(HWND, "04-还原后-对话态.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
