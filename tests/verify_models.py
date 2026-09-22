"""MiniYuxi 多模型助手 · Playwright e2e 验证。

依赖：服务已在 http://127.0.0.1:8801 运行（start_miniyuxi.bat）。
验证项：模型中心打开与渲染、路由条四模式、多模型对比切换、右侧模型任务 Tab、
一次真实「自动路由」对话（确认前端 send() 多模型分支闭环）、无前端运行时错误。
用法：python verify_models.py
"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8801"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        pg.goto(BASE, wait_until="networkidle")
        pg.wait_for_timeout(1000)

        # 1) 顶部「模型切换」→ 模型中心
        try:
            pg.locator("#topNav").get_by_text("模型切换", exact=True).first.click(timeout=5000)
            pg.wait_for_selector("#featureModal:not([hidden])", timeout=5000)
            pg.wait_for_selector(".mx-strat", timeout=8000)
            strat_n = pg.locator(".mx-strat").count()
            model_n = pg.locator("#fmBody .mx-card").count()
            check("模型中心-策略三档渲染", strat_n == 3, f"{strat_n} 档")
            check("模型中心-模型卡片渲染", model_n > 0, f"{model_n} 个模型")

            avail = pg.locator("#fmBody .mx-card.ready")
            if avail.count() >= 2:
                avail.nth(0).click(modifiers=["Control"])
                avail.nth(1).click(modifiers=["Control"])
                cmp_n = pg.locator("#fmBody .mx-card.cmp").count()
                check("模型中心-对比勾选可用", cmp_n >= 2, f"{cmp_n} 个加入对比")
            else:
                check("模型中心-对比勾选可用", False, "可用模型不足 2 个")

            pg.click("#fmModelApply", timeout=5000)
            pg.wait_for_timeout(400)
            check("模型中心-应用并关闭", pg.locator("#featureModal").is_hidden())
        except Exception as e:
            check("模型中心-打开与渲染", False, str(e)[:200])

        # 2) 发起一次真实对话，进入对话态（路由条随之可见）
        try:
            pg.locator("#composerInput").click(timeout=5000)
            pg.keyboard.type("用 Python 写一个快速排序，并说明时间复杂度。", delay=10)
            pg.click("#btnSend", timeout=5000)
            pg.wait_for_selector("#messageList .msg-bubble", timeout=8000)
            pg.wait_for_function(
                "document.querySelector('#messageList .msg-bubble') && "
                "document.querySelector('#messageList .msg-bubble').textContent.trim().length > 0",
                timeout=30000,
            )
            bubble = pg.locator("#messageList .msg-bubble").last
            txt = (bubble.inner_text() or "").strip()
            check("对话-助手回复渲染", len(txt) > 0, f"{len(txt)} 字")
        except Exception as e:
            check("对话-助手回复渲染", False, str(e)[:200])

        # 3) 路由条四模式 + 切换到对比
        try:
            check("模型路由条可见", pg.locator("#modelBar").is_visible())
            seg_n = pg.locator("#mxSeg button").count()
            check("路由条四模式", seg_n == 4, f"{seg_n} 个")
            pg.click('#mxSeg button[data-mode="compare"]', timeout=5000)
            pg.wait_for_timeout(300)
            cls = pg.locator('#mxSeg button[data-mode="compare"]').get_attribute("class") or ""
            check("切换到多模型对比模式", "on" in cls)
            # 切回自动路由，准备真实多模型对话
            pg.click('#mxSeg button[data-mode="auto"]', timeout=5000)
            pg.wait_for_timeout(200)
        except Exception as e:
            check("路由条-模式切换", False, str(e)[:200])

        # 4) 真实「自动路由」对话（确认前端 send() 多模型分支闭环）
        try:
            pg.click('#mxSeg button[data-mode="auto"]', timeout=5000)
            pg.wait_for_timeout(300)
            dock = pg.locator("#composerInputDock")
            for attempt in range(2):
                try:
                    dock.click(timeout=5000, force=True)
                    dock.type("解释一下劳动法里事实劳动关系的三个认定要件。", delay=15)
                    pg.wait_for_function("!document.querySelector('#btnSendDock').disabled", timeout=15000)
                    break
                except Exception:
                    if attempt == 1:
                        raise
                    pg.wait_for_timeout(500)
            pg.click("#btnSendDock", timeout=5000)
            pg.wait_for_function(
                "(() => { const n=document.querySelectorAll('#messageList .msg-bubble'); "
                "const b=n[n.length-1]; return b && b.textContent.trim().length>0; })()",
                timeout=30000,
            )
            txt = (pg.locator("#messageList .msg-bubble").last.inner_text() or "").strip()
            check("自动路由对话-前端分支闭环", len(txt) > 0, f"{len(txt)} 字")
        except Exception as e:
            check("自动路由对话-前端分支闭环", False, str(e)[:200])

        # 5) 右侧「模型任务」Tab
        try:
            pg.click('#detailTabs .detail-tab[data-tab="models"]', timeout=5000)
            pg.wait_for_selector("#panelModelTasks:not([hidden])", timeout=5000)
            check("模型任务面板显示", pg.locator("#panelModelTasks").is_visible())
        except Exception as e:
            check("模型任务Tab", False, str(e)[:200])

        check("无前端运行时错误", len(errs) == 0, "; ".join(errs[:3]))

        b.close()

    npass = sum(1 for _, ok in results if ok)
    print(f"\n结果：{npass}/{len(results)} 通过")
    sys.exit(0 if npass == len(results) else 1)


if __name__ == "__main__":
    main()
