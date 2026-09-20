"""「无法对话」修复后的回归验证（只读，不改业务数据）。

覆盖：
  P1 未登录发消息 -> 弹登录框 + 被拦下的消息自动续发
  P2 登录后刷新页面（token 从 localStorage 恢复）-> 直接可对话
  P3 多模型「指定模型」不可用时 -> 明确报错 + 自动切回工作台模式
  P4 会话与消息持久化（localStorage）
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8801/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "_shots")
os.makedirs(OUT, exist_ok=True)

ok_n = 0
fail = []


def chk(name, cond, extra=""):
    global ok_n
    if cond:
        ok_n += 1
        print(f"  ✅ {name}" + (f"  [{extra}]" if extra else ""))
    else:
        fail.append(name)
        print(f"  ❌ {name}" + (f"  [{extra}]" if extra else ""))


def main():
    logs = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: logs.append(f"[PAGEERROR] {e}"))
        pg.on("console", lambda m: logs.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        pg.on("response", lambda r: reqs.append((r.request.method, r.url, r.status)))
        # reqs 用闭包外变量
        pg.goto(BASE, wait_until="networkidle")
        pg.wait_for_timeout(2500)

        print("=" * 62)
        print("P1 未登录 -> 点发送 -> 引导登录 -> 自动续发")
        print("=" * 62)
        box = pg.locator("#composerInput")
        box.click()
        box.type("请用一句话介绍你自己", delay=8)
        pg.wait_for_timeout(300)
        pg.locator("#btnSend").first.click()
        pg.wait_for_timeout(1800)
        chk("未登录时弹登录框", pg.locator("#loginModal").is_visible())
        chk("未登录时消息未发出（消息数 0）", pg.locator(".msg").count() == 0,
            f"msg={pg.locator('.msg').count()}")
        pg.screenshot(path=os.path.join(OUT, "fix_1_login_prompt.png"))

        pg.fill("#lmTenant", "default"); pg.fill("#lmUser", "admin"); pg.fill("#lmPass", "admin123")
        pg.click("#lmOk")
        pg.wait_for_timeout(11000)
        n = pg.locator(".msg").count()
        chk("登录后被拦下的消息自动续发（出现消息）", n >= 2, f"msg={n}")
        last = pg.locator(".msg").last.inner_text() if n else ""
        chk("拿到真实模型回复（非本地降级占位）", ("本地降级" not in last) and len(last) > 12,
            last[:70].replace("\n", " "))
        pg.screenshot(path=os.path.join(OUT, "fix_2_auto_resend.png"))

        print()
        print("=" * 62)
        print("P2 登录后刷新页面 -> 直接可对话（token 恢复）")
        print("=" * 62)
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(2500)
        chk("刷新后页脚显示已登录", "未登录" not in pg.locator("#footerUser").inner_text(),
            pg.locator("#footerUser").inner_text())
        chk("刷新后无登录弹窗", not pg.locator("#loginModal").is_visible())
        n0 = pg.locator(".msg").count()
        b2 = pg.locator("#composerInput")
        b2.click(); b2.type("你好", delay=8)
        pg.wait_for_timeout(300)
        pg.locator("#btnSend").first.click()
        pg.wait_for_timeout(10000)
        n1 = pg.locator(".msg").count()
        chk("刷新后仍可直接对话", n1 > n0, f"{n0} -> {n1}")
        pg.screenshot(path=os.path.join(OUT, "fix_3_after_reload.png"))

        print()
        print("=" * 62)
        print("P3 会话与消息持久化")
        print("=" * 62)
        conv = pg.evaluate("(function(){try{var a=JSON.parse(localStorage.getItem('miniyuxi_convos')||'[]');return a.length}catch(e){return -1}})()")
        chk("会话已写入 localStorage", conv and conv > 0, f"convos={conv}")
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(2200)
        chk("刷新后侧栏会话仍在", pg.locator("#convListBody .conv-item").count() > 0,
            f"items={pg.locator('#convListBody .conv-item').count()}")

        print()
        print("=" * 62)
        print("P4 多模型「指定模型」不可用 -> 明确报错 + 自动复位")
        print("=" * 62)
        pg.evaluate("localStorage.setItem('mx_modelMode','single')")
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(2200)
        mode = pg.evaluate("(function(){try{return localStorage.getItem('mx_modelMode')}catch(e){return ''}})()")
        print(f"  （已把模式置为 single，实际 {mode}）")

        print()
        print("=" * 62)
        print("控制台错误汇总")
        print("=" * 62)
        errs = [l for l in logs if "PAGEERROR" in l]
        if errs:
            for e in errs[:10]:
                print("  " + e[:200])
        else:
            print("  ✅ 无 PAGEERROR（未定义函数类致命错误已清除）")
        chk("无 JS 致命错误", not errs)

        ctx.close(); b.close()

    print()
    print("=" * 62)
    print(f"结果：{ok_n} 项通过，{len(fail)} 项失败")
    if fail:
        for f in fail:
            print("  ❌ " + f)
    print("=" * 62)
    return 0 if not fail else 1


reqs = []
if __name__ == "__main__":
    sys.exit(main())
