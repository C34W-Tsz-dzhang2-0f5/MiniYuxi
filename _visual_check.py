"""前端收口视觉验证：多视口截图 + 控制台错误采集 + 交互断言（只读，不改数据）。"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8801/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "_shots")
os.makedirs(OUT, exist_ok=True)

errors = []
results = []


def chk(label, cond, extra=""):
    results.append((label, bool(cond), extra))


with sync_playwright() as p:
    browser = p.chromium.launch()

    def page_at(w, h, name, dark=False, actions=None):
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  device_scale_factor=1)
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append("[console.%s] %s" % (m.type, m.text))
              if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errors.append("[pageerror] %s" % e))
        pg.goto(BASE, wait_until="networkidle")
        if dark:
            pg.evaluate("document.body.classList.add('dark');document.body.classList.remove('light')")
        pg.wait_for_timeout(700)
        if actions:
            actions(pg)
            pg.wait_for_timeout(500)
        pg.screenshot(path="%s/%s.png" % (OUT, name), full_page=False)
        return pg, ctx

    # ---- 1. 桌面 1440 ----
    pg, ctx = page_at(1440, 900, "1_desktop_1440")
    chk("1440 标题可见", pg.locator(".wb-home-title").is_visible())
    chk("1440 多模型条可见（首屏）", pg.locator("#modelBar").is_visible())
    mb = pg.locator("#modelBar").bounding_box()
    chk("1440 路由条在首屏内(y<900)", mb and mb["y"] < 900, str(mb and round(mb["y"])))
    chk("1440 侧栏品牌含 SVG 图标",
        pg.locator(".conversation-list-brand .brand-logo-mark").count() >= 1)
    chk("1440 右栏常显（非抽屉态）",
        pg.evaluate("!document.getElementById('detailPanelContainer').classList.contains('is-drawer-open')"))
    chk("1440 抽屉开关隐藏", not pg.locator("#btnDetailDrawer").is_visible())
    n_vis = pg.evaluate("""Array.from(document.querySelectorAll('#topNav .cloud-welcome__nav-item'))
        .filter(e=>e.offsetParent!==null).length""")
    chk("1440 导航条目全部可见", n_vis == 8, "可见 %d 条" % n_vis)
    chk("1440 更多按钮隐藏", not pg.locator("#btnNavMore").is_visible())
    ctx.close()

    # ---- 2. ≤1279 断点：nav 溢出（右栏仍是内联，抽屉断点是 1024） ----
    pg, ctx = page_at(1100, 800, "2_tablet_1100")
    n_vis = pg.evaluate("""Array.from(document.querySelectorAll('#topNav .cloud-welcome__nav-item'))
        .filter(e=>e.offsetParent!==null).length""")
    chk("1100 导航收敛为 4 条", n_vis == 4, "可见 %d 条" % n_vis)
    chk("1100 更多按钮可见", pg.locator("#btnNavMore").is_visible())
    chk("1100 右栏仍内联（>1024 不进抽屉）",
        pg.evaluate("getComputedStyle(document.getElementById('detailPanelContainer')).position") == "static",
        pg.evaluate("getComputedStyle(document.getElementById('detailPanelContainer')).position"))
    pg.click("#btnNavMore")
    pg.wait_for_timeout(300)
    chk("1100 更多菜单可展开", pg.locator("#navMoreMenu").is_visible())
    menu_box = pg.locator("#navMoreMenu").bounding_box()
    chk("1100 更多菜单未被裁切（宽>100）", menu_box and menu_box["width"] > 100,
        str(menu_box and round(menu_box["width"])))
    pg.screenshot(path="%s/3_tablet_1100_navmore.png" % OUT)
    ctx.close()

    # ---- 3. ≤1024 断点：右栏转抽屉 ----
    pg, ctx = page_at(900, 800, "4_narrow_900_drawer_open", actions=lambda p: p.click("#btnDetailDrawer"))
    chk("900 抽屉开关可见", pg.locator("#btnDetailDrawer").is_visible())
    chk("900 点开关后抽屉打开",
        pg.evaluate("document.getElementById('detailPanelContainer').classList.contains('is-drawer-open')"))
    chk("900 遮罩可见", pg.locator("#detailPanelDrawerBackdrop").is_visible())
    chk("900 抽屉实际推入视口",
        pg.evaluate("document.getElementById('detailPanelContainer').getBoundingClientRect().right") <= 901,
        str(round(pg.evaluate("document.getElementById('detailPanelContainer').getBoundingClientRect().right"))))
    pg.screenshot(path="%s/4_narrow_900_drawer_open.png" % OUT)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    chk("900 Esc 关闭抽屉",
        pg.evaluate("!document.getElementById('detailPanelContainer').classList.contains('is-drawer-open')"))
    chk("900 关闭后抽屉移出视口",
        pg.evaluate("document.getElementById('detailPanelContainer').getBoundingClientRect().left") >= 899)
    ctx.close()

    # ---- 4. 移动端 390 ----
    pg, ctx = page_at(390, 844, "5_mobile_390")
    chk("390 更多按钮仍可达（nav 未整块隐藏）", pg.locator("#btnNavMore").is_visible())
    chk("390 抽屉开关可达", pg.locator("#btnDetailDrawer").is_visible())
    chk("390 路由条可见", pg.locator("#modelBar").is_visible())
    chk("390 侧栏折叠态不溢出（品牌文字隐藏）",
        pg.evaluate("""(()=>{var e=document.querySelector('.conversation-list-collapsed-top .brand-wordmark');
            return !e || getComputedStyle(e).display==='none';})()"""))
    ctx.close()

    # ---- 5. 暗色主题 ----
    pg, ctx = page_at(1440, 900, "6_dark_1440", dark=True)
    bg = pg.evaluate("getComputedStyle(document.body).backgroundColor")
    chk("暗色主题生效（背景偏深）", bg not in ("rgb(242, 242, 242)", "rgba(0, 0, 0, 0)"), bg)
    ctx.close()

    browser.close()

print("=== 交互 / 视觉断言 ===")
ok = True
for label, cond, extra in results:
    if not cond:
        ok = False
    print("   %s %s %s" % ("✓" if cond else "✗", label, extra))

print("\n=== 控制台错误/警告 ===")
if errors:
    for e in errors[:25]:
        print("   ! " + e[:220])
    ok = False if any("pageerror" in e for e in errors) else ok
else:
    print("   （无）")

print("\nVISUAL PASSED" if ok else "\nVISUAL FAILED")
sys.exit(0 if ok else 1)
