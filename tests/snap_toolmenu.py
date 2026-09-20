from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://127.0.0.1:8801", wait_until="networkidle")
    pg.wait_for_timeout(800)
    pg.click("#btnToolMenu")
    pg.wait_for_timeout(500)
    pg.screenshot(path="snap_toolmenu.png")
    b.close()
    print("snap_toolmenu.png saved")
