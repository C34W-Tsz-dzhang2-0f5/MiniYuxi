"""对 WorkBuddy 桌面端窗口做截图取证（阿长 2026-09-24 授权）。

流程：定位窗口 → 还原（若最小化）→ 置顶 → 等待重绘 → 按窗口矩形抓图。
只依赖 ctypes + Pillow，不用 pywin32。

用法：
    python scripts/_win_shot.py --list                 # 只列候选窗口
    python scripts/_win_shot.py -o out.png             # 自动挑最大的 WorkBuddy 窗口
    python scripts/_win_shot.py --hwnd 133676 -o a.png # 指定窗口
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shcore = ctypes.windll.shcore

SW_RESTORE = 9
SW_SHOW = 5

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def set_dpi_aware() -> None:
    """让 GetWindowRect / ImageGrab 都用物理像素，避免缩放错位。"""
    try:
        shcore.SetProcessDpiAwareness(2)      # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def proc_name(hwnd: int) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wt.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return "?"
    finally:
        kernel32.CloseHandle(h)


def window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def rect_of(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def candidates() -> list[tuple[int, str, str, int, int]]:
    out: list[tuple[int, str, str, int, int]] = []

    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        exe = proc_name(hwnd)
        if "workbuddy" not in exe.lower():
            return True
        _x, _y, w, h = rect_of(hwnd)
        out.append((hwnd, window_title(hwnd), exe, w, h))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def activate(hwnd: int) -> None:
    """还原 + 置顶。Electron 有 SetForegroundWindow 限制，用 AttachThreadInput 兜底。"""
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out")
    ap.add_argument("--hwnd", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--settle", type=float, default=1.6, help="置顶后等待重绘秒数")
    ap.add_argument("--crop-bottom", type=int, default=0, help="截掉底部像素（如任务栏重叠）")
    args = ap.parse_args()

    set_dpi_aware()
    cands = candidates()
    if args.list or (not args.out and not args.hwnd):
        print(f"{'hwnd':>10}  {'exe':<20} {'size':>12}  title")
        print("-" * 84)
        for hwnd, title, exe, w, h in cands:
            print(f"{hwnd:>10}  {exe:<20} {w:>5}x{h:<6}  {title[:48]}")
        if not args.out:
            return 0

    if args.hwnd:
        hwnd = args.hwnd
    else:
        real = [c for c in cands if c[3] > 400 and c[4] > 300]
        pool = real or cands
        if not pool:
            raise SystemExit("✗ 没找到 WorkBuddy 窗口")
        hwnd = max(pool, key=lambda c: c[3] * c[4])[0]

    activate(hwnd)
    time.sleep(args.settle)

    x, y, w, h = rect_of(hwnd)
    if args.crop_bottom:
        h = max(1, h - args.crop_bottom)
    if w < 200 or h < 150:
        print(f"⚠️ 窗口仍偏小（{w}x{h}），可能没还原成功")

    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"✓ hwnd={hwnd} rect=({x},{y},{w}x{h}) → {out}")
    print(f"  标题：{window_title(hwnd)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
