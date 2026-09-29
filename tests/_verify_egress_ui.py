# -*- coding: utf-8 -*-
"""数据出境管控 · 前端面板验证（真实服务 + Playwright + 截图）。

自包含：自己拉起 run.py（独立端口 + 独立临时库），先经 API 制造两条真实出境日志
（一条放行、一条被拒），再打开「数据出境」面板断言渲染，最后截图。

用法：.venv/Scripts/python.exe tests/_verify_egress_ui.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %-52s %s" % ("OK " if ok else "XX ", name, detail))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, url, token="", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def main():
    from playwright.sync_api import sync_playwright

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp(prefix="mx-egress-ui-")
    env = dict(os.environ)
    env["MINIYUXI_DATA_DIR"] = tmp
    env["MINIYUXI_DB"] = os.path.join(tmp, "ui.db")
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("MINIYUXI_EGRESS_LLM", "MINIYUXI_EGRESS_EMBEDDING", "MINIYUXI_EGRESS_SEARCH",
              "MINIYUXI_EGRESS_EXTERNAL_RAG", "MINIYUXI_EGRESS_CONNECTOR",
              "MINIYUXI_EGRESS_LOCKDOWN", "LLM_API_KEY"):
        env.pop(k, None)

    print(f"[启动] run.py --port {port}")
    proc = subprocess.Popen([PY, os.path.join(ROOT, "run.py"), "--port", str(port), "--no-open"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(90):
            if proc.poll() is not None:
                break
            try:
                st, js = http("GET", f"{base}/api/health", timeout=2)
                if st == 200 and js.get("ok"):
                    ok = True
                    break
            except Exception:
                time.sleep(0.5)
        if not ok:
            out = b""
            try:
                out = proc.stdout.read(4000) if proc.stdout else b""
            except Exception:
                pass
            print("服务未启动：\n" + out.decode("utf-8", "ignore")[-1500:])
            return 2

        st, js = http("POST", f"{base}/api/auth/login",
                      body={"tenant": "default", "username": "admin", "password": "admin123"})
        tok = js.get("token", "")
        if not tok:
            print("登录失败：%s" % js)
            return 2

        # ---- 制造两条真实出境日志：一条放行、一条被拒 ----
        http("POST", f"{base}/api/egress/preset", token=tok, body={"name": "balanced"})
        http("POST", f"{base}/api/tools/call", token=tok,
             body={"name": "web_search", "args": {"query": "2026年深圳社保缴费基数"}})
        http("POST", f"{base}/api/egress/preset", token=tok, body={"name": "lockdown"})
        # 载荷里故意放一个身份证号：用于断言「日志脱敏」在 UI 上真的生效
        http("POST", f"{base}/api/tools/call", token=tok,
             body={"name": "web_search",
                   "args": {"query": "员工工资表 440301199001011234"}})
        http("POST", f"{base}/api/egress/preset", token=tok, body={"name": "balanced"})
        st, js = http("GET", f"{base}/api/egress/log?limit=20", token=tok)
        n_logs = len(js.get("logs", []))
        check("API 侧已产生出境日志", n_logs >= 2, f"n={n_logs}")

        # ---- 浏览器 ----
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                        args=["--no-sandbox"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 960})
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))

            page.goto(base + "/", wait_until="domcontentloaded")
            page.evaluate("t => localStorage.setItem('miniyuxi_token', t)", tok)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            # 导航项已注册（「更多」子菜单里应有 data-rail-sub="egress"）
            has_nav = page.evaluate(
                "() => !!document.querySelector('#navRail [data-rail=\"more\"]')")
            check("侧栏「更多」菜单存在", has_nav)

            # 走真实点击路径：更多 -> 数据出境
            page.evaluate("""() => {
                const more = document.querySelector('#navRail .nav-rail__item[data-rail="more"]');
                if (more) more.click();
            }""")
            page.wait_for_timeout(300)
            found = page.evaluate(
                "() => !!document.querySelector('#railSub_more .nav-rail__sub-item[data-rail-sub=\"egress\"]')")
            check("子菜单含「数据出境」项", found)
            page.evaluate("""() => {
                const b = document.querySelector('#railSub_more .nav-rail__sub-item[data-rail-sub="egress"]');
                if (b) b.click();
            }""")

            # 面板出现
            page.wait_for_selector("#featureModal:not([hidden])", timeout=8000)
            title = page.text_content("#fmTitle") or ""
            check("面板已打开", "数据出境" in title, f"title={title!r}")

            # 三档姿态预设
            page.wait_for_function(
                "() => document.querySelectorAll('#egPresets .kb-domain').length >= 3", timeout=8000)
            n_preset = page.evaluate("() => document.querySelectorAll('#egPresets .kb-domain').length")
            check("渲染 3 档姿态预设", n_preset == 3, f"n={n_preset}")
            preset_text = page.text_content("#egPresets") or ""
            check("预设名称含「严格」「锁死」",
                  "严格" in preset_text and "锁死" in preset_text, preset_text.strip()[:80])

            # 5 类目的地
            page.wait_for_function(
                "() => document.querySelectorAll('#egClasses .mkt-card').length === 5", timeout=8000)
            n_cls = page.evaluate("() => document.querySelectorAll('#egClasses .mkt-card').length")
            check("渲染 5 类目的地", n_cls == 5, f"n={n_cls}")
            cls_text = page.text_content("#egClasses") or ""
            check("含机密/内部/公开三级模式标签",
                  all(k in cls_text for k in ("机密", "内部", "公开")), "")
            check("含收口点文件路径", "core/gateway.py" in cls_text, "")
            check("含载荷说明（文档原文）", "文档原文" in cls_text, "")

            # 日志
            page.wait_for_function(
                "() => document.querySelectorAll('#egLogs .mkt-card').length >= 1", timeout=8000)
            n_log = page.evaluate("() => document.querySelectorAll('#egLogs .mkt-card').length")
            check("出境日志已渲染", n_log >= 1, f"n={n_log}")
            log_text = page.text_content("#egLogs") or ""
            check("日志含放行记录", "allow" in log_text, "")
            check("日志含被拒记录（可审计被拒行为）", "deny" in log_text, "")
            # 脱敏在 UI 上真的生效：载荷里的身份证号被替换成 [身份证]，原文不出现
            check("日志脱敏生效（显示 [身份证] 而非原文）",
                  "[身份证]" in log_text and "440301199001011234" not in log_text,
                  f"含占位={'[身份证]' in log_text}")

            # 切预设：点「锁死」应把 llm 变成禁止
            page.evaluate("""() => {
                const bs = document.querySelectorAll('#egPresets .kb-domain');
                for (const b of bs) { if (b.textContent.indexOf('锁死') >= 0) { b.click(); return; } }
            }""")
            page.wait_for_timeout(1200)
            after = page.text_content("#egClasses") or ""
            check("切「锁死」后全部变禁止", after.count("禁止") >= 5, f"禁止出现 {after.count('禁止')} 次")

            # 复位为均衡，便于截图展示正常态
            page.evaluate("""() => {
                const bs = document.querySelectorAll('#egPresets .kb-domain');
                for (const b of bs) { if (b.textContent.indexOf('均衡') >= 0) { b.click(); return; } }
            }""")
            page.wait_for_timeout(1200)

            real_errs = [e for e in errs if "favicon" not in e.lower()]
            check("无 pageerror", not real_errs, str(real_errs[:2]))

            shot = os.path.join(ROOT, "docs", "_shots", "miniyuxi-egress-20260924", "01-panel.png")
            os.makedirs(os.path.dirname(shot), exist_ok=True)
            page.screenshot(path=shot)
            print("     截图: %s" % shot)
            browser.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    print()
    print("=" * 72)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项: %s" % FAIL)
    print("=" * 72)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
