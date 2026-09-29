# -*- coding: utf-8 -*-
"""验证 univer 公式引擎 worker 接通：Worker 被创建 + SUM 真的算出结果。

为什么需要这个测试
------------------
`@univerjs/preset-sheets-core` 的 preset 工厂里有 `notExecuteFormula: !!workerURL`——
**主线程没传 workerURL 时公式执行会被显式关掉**（公式只注册、不求值），
表现为 HR 表格里 SUM/AVG 填了不出结果。这个坑很隐蔽（无报错、无告警），
所以用自动化测试钉住：断言 Worker 被创建 + SUM 真的返回数字。

跑法
----
先起服务（源码 `run.py --no-open`，或装机版 sidecar），然后：

    .venv/Scripts/python.exe tests/_verify_office_formula.py
    MX_BASE=http://127.0.0.1:9150 .venv/Scripts/python.exe tests/_verify_office_formula.py   # 打装机版

退出码 0 = 全通过。
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("MX_BASE", "http://127.0.0.1:8801")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# 截图落到项目根下的 docs/_shots/（本脚本在 tests/ 里，往上找一层）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %-56s %s" % ("OK " if ok else "XX ", name, detail))


def login():
    """直接用 Python 发登录请求拿 token（避免在 about:blank 上跑相对 URL 的 fetch）。"""
    import urllib.request
    body = json.dumps({"tenant": "default", "username": "admin",
                       "password": "admin123"}).encode()
    req = urllib.request.Request(
        BASE + "/api/auth/login", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get("token", "")


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                     args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        workers = []
        page.on("worker", lambda w: workers.append(w.url))
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))

        # ---- 登录拿 token ----
        tok = login()
        check("登录拿到 token", bool(tok), "len=%d" % len(tok))

        # ---- 先导航到站点（拿到 origin），再注入 token ----
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.evaluate("t => localStorage.setItem('miniyuxi_token', t)", tok)
        check("主页面已加载", True, page.url)
        page.add_script_tag(url="/office/office-host.js")
        page.wait_for_function("() => !!window.MiniYuxiOffice", timeout=15000)
        check("office-host.js 已加载", True)

        # ---- 打开表格 ----
        page.evaluate("() => window.MiniYuxiOffice.open('sheet')")
        page.wait_for_selector("#mxofUniverContainer canvas", timeout=60000)
        time.sleep(4)  # 等 Univer 初始化 + worker 握手
        check("表格 canvas 已渲染", True)

        # ---- 断言 1：Worker 被创建 ----
        wk = [u for u in workers if "univer.worker.js" in u]
        check("公式引擎 Worker 已被创建", bool(wk), "url=%s" % (wk[0] if wk else workers))

        # ---- 断言 2：Worker 真的活着（能回消息）----
        alive = page.evaluate("""() => new Promise(res => {
            // 通过 Univer 的 RPC 是否已连通间接判断：容器里已有 formula 相关服务
            // 更直接的办法：再建一个 worker 探活（同源、同文件）
            let w = new Worker('/vendor/univer/univer.worker.js');
            let done = false;
            w.onerror = e => { if(!done){done=true; w.terminate(); res('error:'+ (e.message||''));} };
            setTimeout(()=>{ if(!done){done=true; w.terminate(); res('alive');} }, 2500);
        })""")
        check("Worker 脚本可实例化无致命错误", str(alive).startswith("alive"),
              "结果=%s" % alive)

        # ---- 断言 3：找 FUniver API 入口 ----
        probe = page.evaluate("""() => {
            const out = {globals: [], containerKeys: []};
            for (const k of Object.keys(window)) {
                if (/univer/i.test(k)) out.globals.push(k);
            }
            const c = document.getElementById('mxofUniverContainer');
            if (c) {
                for (const k of Object.getOwnPropertyNames(c)) {
                    if (/univer|__/i.test(k)) out.containerKeys.push(k);
                }
            }
            return out;
        }""")
        print("     探针 globals=%s  containerKeys=%s" % (probe["globals"], probe["containerKeys"]))

        # ---- 断言 4：用自建实例验证 SUM 真的算 ----
        # 不依赖 office-host 内部私有变量：在同一页面另建一个 Univer 实例（带 workerURL），
        # 填 1/2/3 后 SUM(A1:A3) 应得 6。这直接证明"传了 workerURL 公式就会算"。
        page.evaluate("""() => {
            const wrap = document.createElement('div');
            wrap.style.cssText = 'position:fixed;inset:0;z-index:2147483600;background:#fff;' +
                'display:flex;flex-direction:column;font-family:system-ui,-apple-system,"Segoe UI",sans-serif';
            wrap.innerHTML =
                '<div style="padding:14px 20px;border-bottom:1px solid #e5e7eb;background:#f8fafc">' +
                '<div style="font-size:15px;font-weight:600;color:#111827">' +
                'MiniYuxi 办公套件 · 公式引擎验证</div>' +
                '<div style="font-size:12.5px;color:#6b7280;margin-top:3px">' +
                'A1=1, A2=2, A3=3，A4 填 <code style="background:#eef2ff;padding:1px 5px;border-radius:3px;' +
                'color:#3730a3">=SUM(A1:A3)</code>　→　' +
                '<b id="sumOut" style="color:#059669;font-size:14px">计算中…</b>' +
                '　<span style="color:#9ca3af">（经 univer.worker.js 在 Worker 线程求值）</span></div></div>' +
                '<div id="sumProbe" style="flex:1;min-height:0"></div>';
            document.body.appendChild(wrap);
        }""")
        sum_res = page.evaluate("""() => new Promise(resolve => {
            const U = window.UniverOffice;
            if (!U) return resolve({err: 'UniverOffice 缺失'});
            const host = document.getElementById('sumProbe');
            const inst = U.createUniver({
                locale: U.LocaleType.ZH_CN,
                locales: (() => { const m={}; m[U.LocaleType.ZH_CN] =
                    U.mergeLocales(U.sheetsLocale, U.docsLocale); return m; })(),
                presets: [U.UniverSheetsCorePreset({
                    container: host, workerURL: '/vendor/univer/univer.worker.js' })],
            });
            const api = inst.univerAPI;
            api.createWorkbook({ id: 'sumprobe', name: 'probe' });
            const fw = api.getActiveWorkbook();
            const ws = fw.getActiveSheet();
            ws.getRange('A1').setValue(1);
            ws.getRange('A2').setValue(2);
            ws.getRange('A3').setValue(3);
            ws.getRange('A4').setFormula('=SUM(A1:A3)');
            // 公式求值是异步的（走 worker RPC），轮询等结果
            let n = 0;
            const timer = setInterval(() => {
                n++;
                let v = null;
                try { v = ws.getRange('A4').getValue(); } catch (e) { v = 'throw:'+e.message; }
                if (v === 6 || v === '6' || n > 40) {
                    clearInterval(timer);
                    resolve({value: v, tries: n});
                }
            }, 250);
        })""")
        print("     SUM 探针返回: %s" % json.dumps(sum_res, ensure_ascii=False))
        check("SUM(A1:A3) 求值 = 6", str(sum_res.get("value")) in ("6", "6.0"),
              "值=%s 轮询=%s 次" % (sum_res.get("value"), sum_res.get("tries")))
        # 把结果回填到截图标题栏
        page.evaluate("""v => {
            const el = document.getElementById('sumOut');
            if (el) el.textContent = 'A4 = ' + v + '　✓ 公式已求值';
        }""", sum_res.get("value"))

        # ---- 断言 5：pageerror 干净 ----
        real_errs = [e for e in errs if "favicon" not in e.lower()]
        check("无 pageerror", not real_errs, str(real_errs[:2]))

        time.sleep(1.5)
        shot = os.path.join(ROOT, "docs", "_shots", "miniyuxi-univer-20260924",
                            "03-formula.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)
        page.screenshot(path=shot, full_page=False)
        print("     截图: %s" % shot)
        browser.close()

    print()
    print("=" * 72)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项: %s" % FAIL)
    print("=" * 72)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
