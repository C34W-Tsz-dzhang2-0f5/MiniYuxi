"""验证：用户此前选了「不可用的指定模型」时，能否明确报错并自动自救。

模拟真实故障：localStorage 里 mx_modelMode=single + mx_singleModelId 指向无 Key 的模型。
只读，不改业务数据。
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8801/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "_shots")
os.makedirs(OUT, exist_ok=True)


def main():
    logs = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: logs.append(str(e)))
        pg.goto(BASE, wait_until="networkidle")
        pg.wait_for_timeout(2200)

        # 登录
        pg.evaluate("""(function(){
          return fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({tenant:'default',username:'admin',password:'admin123'})})
            .then(r=>r.json()).then(d=>{ if(d.token) localStorage.setItem('miniyuxi_token', d.token); });
        })()""")
        pg.wait_for_timeout(2000)

        # 制造故障现场：指定一个无 Key 服务商的模型
        pg.evaluate("""(function(){
          localStorage.setItem('mx_modelMode','single');
          localStorage.setItem('mx_singleModelId','deepseek-chat');   // 会路由到未配置 Key 的 siliconflow
        })()""")
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(2500)

        print("=" * 62)
        print("故障注入：modelMode=single, singleModelId=deepseek-chat（无 Key）")
        print("=" * 62)
        print("  当前模式:", pg.evaluate("localStorage.getItem('mx_modelMode')"))

        box = pg.locator("#composerInput")
        if box.count() and box.is_visible():
            box.click()
            box.type("你好", delay=8)
        pg.wait_for_timeout(300)
        btns = pg.locator("#btnSend")
        if btns.count():
            btns.first.click()
        pg.wait_for_timeout(8000)

        msgs = pg.locator(".msg")
        n = msgs.count()
        print(f"  消息数: {n}")
        body = pg.locator("#messageList").inner_text()
        print("  消息区文本[:300]:", body[:300].replace("\n", " / "))

        print()
        print("=" * 62)
        print("断言")
        print("=" * 62)
        res = []
        res.append(("给出可读的失败原因（未静默成「无返回」）",
                    ("尚未配置" in body) or ("Key" in body) or ("不可用" in body)))
        res.append(("不再是空白气泡", body.strip() != ""))
        after = pg.evaluate("localStorage.getItem('mx_modelMode')")
        res.append(("已自动切回工作台模式", after == "workbench"))
        res.append(("无 JS 致命错误", not logs))

        pg.screenshot(path=os.path.join(OUT, "fix_4_model_unavailable.png"))

        nfail = 0
        for name, cond in res:
            print(("  ✅ " if cond else "  ❌ ") + name +
                  (f"   [mode={after}]" if "工作台" in name else ""))
            if not cond:
                nfail += 1
        if logs:
            print("  JS 错误:", logs[:3])

        ctx.close(); b.close()
        return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
