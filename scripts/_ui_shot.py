"""对 MiniYuxi 工作台做界面截图（源码运行态，用于核对改造效果）。

用法：
    python scripts/_ui_shot.py --port 8801 -o docs/_shots/miniyuxi-live
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))


def pick_browser() -> dict:
    """复用验收脚本的浏览器探测逻辑（返回 {"executable_path": ...}）。"""
    try:
        from _acceptance_desktop import pick_browser as _pb
        got = _pb()
        if got:
            return got
    except Exception:
        pass
    import glob
    import os
    cands = sorted(glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "ms-playwright", "chromium-*", "chrome-win*", "chrome.exe")))
    if cands:
        return {"executable_path": cands[-1]}
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if Path(p).exists():
            return {"executable_path": p}
    raise SystemExit("✗ 找不到可用浏览器")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("-o", "--outdir", default="docs/_shots/miniyuxi-live")
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    out = (REPO / args.outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{args.port}/"

    with sync_playwright() as pw:
        br = pw.chromium.launch(**pick_browser(), args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        if args.token:
            pg.add_init_script(f"try{{localStorage.setItem('miniyuxi_token',{args.token!r});}}catch(e){{}}")
        pg.goto(url, wait_until="load", timeout=30000)
        pg.wait_for_timeout(2200)

        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        # ① 默认态（侧边栏折叠）
        pg.screenshot(path=str(out / "01-默认折叠态.png"))

        # ② 展开侧边栏 → 看左侧主导航
        try:
            pg.click("#btnExpand", timeout=4000)
            pg.wait_for_timeout(900)
        except Exception as e:
            print("  ⚠ 展开侧边栏失败:", e)
        pg.screenshot(path=str(out / "02-展开态-左侧主导航.png"))

        # ③ 点「专家·技能·连接器」看二级菜单
        try:
            pg.click('#navRail .nav-rail__item[data-rail="market"]', timeout=4000)
            pg.wait_for_timeout(700)
            pg.screenshot(path=str(out / "03-二级菜单.png"))
        except Exception as e:
            print("  ⚠ 二级菜单失败:", e)

        # ④ 场景 tab 三组
        try:
            tabs = pg.eval_on_selector_all("#sceneTabs > *", "els => els.map(e => e.textContent.trim())")
            print("  场景 tab:", tabs)
            chips = pg.eval_on_selector_all("#quickActions .quick-actions__item",
                                            "els => els.map(e => e.dataset.name)")
            print("  当前 chips:", chips)
            # 切到「设计创意」
            pg.click("#sceneTabs >> text=设计创意", timeout=4000)
            pg.wait_for_timeout(600)
            chips2 = pg.eval_on_selector_all("#quickActions .quick-actions__item",
                                             "els => els.map(e => e.dataset.name)")
            print("  设计创意 chips:", chips2)
            pg.screenshot(path=str(out / "04-设计创意场景.png"))
        except Exception as e:
            print("  ⚠ 场景切换失败:", e)

        # ⑤ 元素存在性断言
        checks = {
            "#navRail": "展开态主导航",
            "#navRailCollapsed": "折叠态主导航",
            "#btnWorkspace": "选择工作空间",
            "#btnAccessChip": "允许完全访问",
        }
        print("\n  元素检查:")
        for sel, name in checks.items():
            try:
                n = pg.eval_on_selector_all(sel, "els => els.length")
                box = pg.eval_on_selector(sel, "el => { const r = el.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }")
                print(f"    {name:<14} {sel:<22} 数量={n} 尺寸={box}")
            except Exception as e:
                print(f"    {name:<14} {sel:<22} ✗ {e}")

        rail_items = pg.eval_on_selector_all("#navRail .nav-rail__item",
                                             "els => els.map(e => e.textContent.trim())")
        print("\n  左侧导航项:", rail_items)
        placeholder = pg.eval_on_selector("#composerInput", "el => el.dataset.placeholder")
        print("  输入框占位:", placeholder)
        print("  pageerror:", errors or "无")

        br.close()
    print(f"\n✓ 截图输出目录：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
