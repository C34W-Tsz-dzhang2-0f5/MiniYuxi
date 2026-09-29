"""枚举当前可见的顶层窗口（标题 + 尺寸 + 进程名），用于定位 WorkBuddy 主窗口。

只用 ctypes，不依赖 pywin32。用法： python scripts/_win_list.py [关键词过滤]
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def proc_name(hwnd: int) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
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


def main() -> int:
    kw = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    rows: list[tuple[int, str, str, int, int, int, int]] = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        exe = proc_name(hwnd)
        if kw and kw not in title.lower() and kw not in exe.lower():
            return True
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        rows.append((hwnd, title, exe, r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    print(f"{'hwnd':>10}  {'exe':<24} {'size':>12}  title")
    print("-" * 100)
    for hwnd, title, exe, _l, _t, w, h in rows:
        print(f"{hwnd:>10}  {exe:<24} {w:>5}x{h:<6}  {title[:56]}")
    print(f"\n共 {len(rows)} 个可见窗口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
