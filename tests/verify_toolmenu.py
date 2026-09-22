"""验证 MiniYuxi 左侧功能菜单（添加文件/引用/模式/专家/技能/连接器/允许完全访问）1:1 还原。"""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8801"
results = []


def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + "  " + name + ("  -> " + detail if detail else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_timeout(800)

    def open_menu():
        hidden = pg.eval_on_selector("#toolMenu", "el => el.hidden")
        if hidden:
            pg.click("#btnToolMenu")
            pg.wait_for_timeout(250)

    # 1. 打开工具菜单
    pg.click("#btnToolMenu")
    pg.wait_for_timeout(300)
    menu_hidden = pg.eval_on_selector("#toolMenu", "el => el.hidden")
    rec("工具菜单可打开", not menu_hidden)
    items = pg.eval_on_selector_all("#toolMenu .tool-menu__item", "els => els.map(e => e.querySelector('.tool-menu__label')?.textContent)")
    rec("含 7 个功能项", len(items) == 7, str(items))

    # 2. 模式
    pg.click('#toolMenu .tool-menu__item[data-action="mode"]')
    pg.wait_for_timeout(300)
    drawer_title = pg.eval_on_selector("#toolDrawerTitle", "el => el.textContent")
    rec("模式抽屉标题", drawer_title == "模式", drawer_title)
    modes = pg.eval_on_selector_all("#toolDrawerBody .tool-menu__option", "els => els.map(e => e.querySelector('.tool-menu__option-title')?.textContent)")
    rec("模式含 Agent/计划/问答", "默认" in modes and "计划" in modes and "问答" in modes, str(modes))
    # 选「计划」
    for m in pg.query_selector_all("#toolDrawerBody .tool-menu__option"):
        if m.eval_on_selector(".tool-menu__option-title", "e=>e.textContent") == "计划":
            m.click(); break
    pg.wait_for_timeout(300)
    mode_hint = pg.eval_on_selector("#modeHint", "el => el.textContent")
    rec("选择计划后 modeHint 更新", mode_hint == "计划", mode_hint)

    # 3. 专家
    open_menu(); pg.wait_for_timeout(150)
    pg.click('#toolMenu .tool-menu__item[data-action="expert"]')
    pg.wait_for_timeout(400)
    exp_items = pg.eval_on_selector_all("#toolDrawerBody .tool-menu__option", "els => els.map(e => e.querySelector('.tool-menu__option-title')?.textContent)")
    rec("专家列表已加载", len(exp_items) >= 1, str(exp_items[:3]))
    if exp_items:
        pg.query_selector("#toolDrawerBody .tool-menu__option").click()
        pg.wait_for_timeout(300)
        exp_hint = pg.eval_on_selector("#expertHint", "el => el.textContent")
        rec("选择专家后 hint 更新", exp_hint != "未选择", exp_hint)

    # 4. 技能
    open_menu(); pg.wait_for_timeout(150)
    pg.click('#toolMenu .tool-menu__item[data-action="skill"]')
    pg.wait_for_timeout(400)
    sk_items = pg.eval_on_selector_all("#toolDrawerBody .tool-menu__option", "els => els.map(e => e.querySelector('.tool-menu__option-title')?.textContent)")
    rec("技能列表已加载", len(sk_items) >= 1, "n=" + str(len(sk_items)))
    if sk_items:
        pg.query_selector("#toolDrawerBody .tool-menu__option").click()
        pg.wait_for_timeout(300)
        sk_hint = pg.eval_on_selector("#skillHint", "el => el.textContent")
        rec("选择技能后 hint 更新", "已选" in sk_hint, sk_hint)

    # 5. 连接器
    open_menu(); pg.wait_for_timeout(150)
    pg.click('#toolMenu .tool-menu__item[data-action="connector"]')
    pg.wait_for_timeout(400)
    conn_items = pg.eval_on_selector_all("#toolDrawerBody .tool-menu__option", "els => els.map(e => e.querySelector('.tool-menu__option-title')?.textContent)")
    rec("连接器列表已加载", len(conn_items) >= 1, str(conn_items[:3]))
    if conn_items:
        pg.query_selector("#toolDrawerBody .tool-menu__option").click()
        pg.wait_for_timeout(300)
        conn_hint = pg.eval_on_selector("#connectorHint", "el => el.textContent")
        rec("选择连接器后 hint 更新", "已选" in conn_hint, conn_hint)

    # 6. 允许完全访问开关（点滑块，因真实 checkbox 为 opacity:0）
    open_menu(); pg.wait_for_timeout(150)
    before = pg.eval_on_selector("#allowFullAccess", "el => el.checked")
    pg.click(".wb-switch__slider")
    pg.wait_for_timeout(200)
    after = pg.eval_on_selector("#allowFullAccess", "el => el.checked")
    rec("允许完全访问开关可切换", before != after, "before=" + str(before) + " after=" + str(after))
    pg.click(".wb-switch__slider"); pg.wait_for_timeout(150)  # 复位

    # 7. 添加文件（用临时文件，验证上传 + ref list）
    import tempfile, os
    tf = os.path.join(tempfile.gettempdir(), "mini_test.txt")
    with open(tf, "w", encoding="utf-8") as f:
        f.write("MiniYuxi 测试文档：车务通招聘流程说明。")
    pg.set_input_files("#fileInput", tf)
    pg.wait_for_timeout(2500)
    refs = pg.eval_on_selector_all("#refListMain .ref-list__item", "els => els.map(e => e.textContent)")
    rec("添加文件后引用列表出现", len(refs) >= 1, str(refs))

    # 8. 发送一条带 问答模式 的消息，验证真实回复
    open_menu(); pg.wait_for_timeout(150)
    # 诊断：菜单状态
    diag = pg.eval_on_selector("#toolMenu", "el => ({hidden: el.hidden, top: el.style.top, left: el.style.left, h: el.offsetHeight})")
    print("DIAG menu:", diag)
    pg.click('#toolMenu .tool-menu__item[data-action="mode"]', timeout=8000); pg.wait_for_timeout(200)
    for m in pg.query_selector_all("#toolDrawerBody .tool-menu__option"):
        if m.eval_on_selector(".tool-menu__option-title", "e=>e.textContent") == "问答":
            m.click(); break
    pg.wait_for_timeout(200)
    pg.fill("#composerInput", "用一句话介绍 MiniYuxi")
    pg.click("#btnSend")
    pg.wait_for_timeout(20000)
    last = pg.eval_on_selector_all("#messageList .msg--assistant .msg-bubble", "els => els.map(e => e.textContent.trim())")
    last_text = last[-1] if last else ""
    rec("对话返回真实回复（非降级）", len(last_text) > 15 and "降级" not in last_text[:20], last_text[:90])

    # 截图
    pg.screenshot(path="verify_toolmenu.png")
    b.close()

ok = sum(1 for _, v, _ in results if v)
print("\n=== %d/%d PASS ===" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
