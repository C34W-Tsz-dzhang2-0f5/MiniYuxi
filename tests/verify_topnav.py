# -*- coding: utf-8 -*-
"""顶部栏功能端到端验证：真实浏览器点开每个入口，检查是否真的有数据/可用。"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8801/"
results = []


def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (" :: " + detail if detail else ""))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console." + m.type + ": " + m.text) if m.type == "error" else None)

    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)

    # 1) 顶部栏条目
    labels = pg.eval_on_selector_all("#topNav .cloud-welcome__nav-item", "els=>els.map(e=>e.textContent.trim())")
    expect = ["新建", "导入", "知识库", "流程", "模型切换", "成本管理", "工作台"]
    rec("顶部栏 7 项与预期一致", labels == expect, "实际=%s" % labels)

    # 2) 自动登录是否成功（localStorage token）
    tok = pg.evaluate("()=>localStorage.getItem('miniyuxi_token')||''")
    rec("静默自动登录已拿到 token", len(tok) > 20, "len=%d" % len(tok))

    def close_modal():
        try:
            pg.click("#fmClose", timeout=3000)
        except Exception:
            pass
        pg.wait_for_timeout(300)

    # 3) 知识库
    pg.click("#topNav .cloud-welcome__nav-item[data-action='kb']")
    pg.wait_for_timeout(2500)
    kb_items = pg.eval_on_selector_all("#fmBody .fm-list li .t", "els=>els.map(e=>e.textContent.trim())")
    rec("知识库弹窗有真实文档", len(kb_items) > 0, "%d 条，首条=%s" % (len(kb_items), kb_items[0][:40] if kb_items else ""))
    close_modal()

    # 4) 模型切换
    pg.click("#topNav .cloud-welcome__nav-item[data-action='model']")
    pg.wait_for_timeout(2500)
    cards = pg.eval_on_selector_all("#fmBody .fm-card .m", "els=>els.map(e=>e.textContent.trim())")
    cur = pg.text_content("#fmCurModel") if pg.query_selector("#fmCurModel") else ""
    rec("模型切换列出可选模型", len(cards) >= 2, "%s / 当前=%s" % (cards, cur))
    if cards:
        pg.click("#fmBody .fm-card >> nth=0")
        pg.wait_for_timeout(400)
    close_modal()

    # 5) 成本管理
    pg.click("#topNav .cloud-welcome__nav-item[data-action='cost']")
    pg.wait_for_timeout(2500)
    cost_rows = pg.eval_on_selector_all("#fmBody .fm-list li .t", "els=>els.map(e=>e.textContent.trim())")
    joined = " | ".join(cost_rows)
    rec("成本管理显示真实用量", len(cost_rows) >= 3 and "¥" in joined, joined[:150])
    close_modal()

    # 6) 流程
    pg.click("#topNav .cloud-welcome__nav-item[data-action='flow']")
    pg.wait_for_timeout(2000)
    opts = pg.eval_on_selector_all("#fmFlowSel option", "els=>els.map(e=>e.textContent.trim())")
    rec("流程下拉有真实流程", len(opts) >= 1, str(opts))
    pg.click("#fmFlowStart")
    pg.wait_for_timeout(2500)
    start_log = pg.text_content("#fmFlowLog")
    rec("流程可启动", "run-" in (start_log or ""), (start_log or "")[:80])
    pg.click("#fmFlowRun")
    pg.wait_for_timeout(4000)
    run_log = pg.text_content("#fmFlowLog")
    rec("流程可跑到结束", "done" in (run_log or ""), (run_log or "")[-80:])
    close_modal()

    # 7) 对话真实可用
    inp = pg.query_selector("#composerInput")
    if inp:
        inp.click()
        pg.keyboard.type("用一句话说明 MiniYuxi 的定位")
        pg.wait_for_timeout(300)
        pg.click("#btnSend")
        pg.wait_for_timeout(30000)
        msgs = pg.eval_on_selector_all("#messageList .wb-msg", "els=>els.map(e=>e.textContent.trim())")
        if not msgs:
            msgs = pg.eval_on_selector_all("#messageList > div", "els=>els.map(e=>e.textContent.trim())")
        last = msgs[-1] if msgs else ""
        rec("对话返回真实回复（非降级）", len(last) > 15 and "离线" not in last[:20], (last[:120] if last else "无回复"))
    else:
        rec("对话输入框存在", False, "未找到 #composerInput")

    # 8) 页面错误
    real_errs = [e for e in errs if "favicon" not in e.lower()]
    rec("无 JS 运行时错误", len(real_errs) == 0, "; ".join(real_errs[:3]))

    pg.screenshot(path="verify_topnav.png", full_page=False)
    b.close()

passed = sum(1 for _, o, _ in results if o)
print("\n==== %d/%d 通过 ====" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
