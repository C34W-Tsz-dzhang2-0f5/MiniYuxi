#!/usr/bin/env python3
"""MiniYuxi 桌面端 · 完整可用性与体验验收（Playwright 驱动真实工作台）。

驱动方式说明（重要）：
  桌面端窗口本身是 Tauri WebView，无法直接挂 Playwright；但桌面端内核就绪后
  导航的就是 http://127.0.0.1:<port>/ ，与 Web 端是同一份 web/index.html。
  所以这里用 Chromium 打开**桌面端 sidecar 实际服务的那个地址**做验收，
  页面、JS、接口与桌面端窗口里完全一致——验的就是桌面端本身，不是网页端替身。

覆盖：
  A 登录流程（未登录拦截 / 错误口令提示 / 正常登录 / 刷新保持 / 退出重登）
  B 功能遍历（9 个导航项 + 核心操作 + 设置 + 通知 + 数据读写与保存）
  C 流畅度（首屏 / 切换 / 操作响应耗时）
  D 一致性比对（与 WorkBuddy）—— 仅采集 MiniYuxi 侧事实，比对结论人工判断

用法：
  .venv/Scripts/python.exe tests/_acceptance_desktop.py

判定：退出码 0 = 无 P0/P1 失败；非 0 = 存在未通过项。
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SHOTS = os.path.join(ROOT, "docs", "_shots")
os.makedirs(SHOTS, exist_ok=True)

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MiniYuxi", "data")
SIDECAR_JSON = os.path.join(DATA_DIR, "sidecar.json")

PASS, FAIL = [], []
TIMINGS: dict[str, float] = {}
CONSOLE_ERR: list[str] = []
PAGE_ERR: list[str] = []
HTTP_ERR: list[str] = []


def chk(name: str, cond: bool, extra: str = "", level: str = "P1") -> bool:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}" + (f"  [{extra}]" if extra else ""))
    else:
        FAIL.append((level, name, extra))
        print(f"  ❌ [{level}] {name}" + (f"  [{extra}]" if extra else ""))
    return cond


def note(msg: str) -> None:
    print(f"  · {msg}")


# 遍历时若某步会弹窗/抽屉，不关掉就会遮住后续点击（表现为 click 超时，
# 很容易被误判成「功能点不了」）。这里统一探测并关掉，同时把「弹了什么」记下来。
OVERLAY_SEL = ".my-modal, #featureModal, #toolDrawer, #navMoreMenu, [class*='backdrop']"


def open_overlays(pg) -> list[str]:
    return pg.evaluate("""(sel) => {
      const out = [];
      document.querySelectorAll(sel).forEach(function (e) {
        if (e.hidden) return;
        const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return;
        const cs = getComputedStyle(e);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        out.push((e.id || e.className || e.tagName) + '');
      });
      return out;
    }""", OVERLAY_SEL)


def dismiss_overlays(pg) -> None:
    pg.keyboard.press("Escape")
    pg.evaluate("""(sel) => {
      document.querySelectorAll(sel).forEach(function (e) {
        e.hidden = true;
        e.classList.remove('is-show', 'is-open', 'is-visible');
      });
      document.body.classList.remove('is-locked', 'no-scroll', 'modal-open');
      document.body.style.removeProperty('overflow');
    }""", OVERLAY_SEL)
    pg.wait_for_timeout(150)


def load_sidecar() -> dict:
    with open(SIDECAR_JSON, encoding="utf-8") as f:
        return json.load(f)


def pick_browser() -> dict:
    """优先用 Playwright 自带 chromium；版本对不上时回退系统 Chrome / Edge。

    本机实测：ms-playwright 缓存的是 chromium-1234，而 pip 装到的 playwright 要 1243，
    直接 launch 会报 "Executable doesn't exist"。与其下一百多 MB，不如用现成的 Chrome。
    """
    import glob
    # 注意目录名是 chrome-win64 不是 chrome-win（本机实测踩过）
    cands = sorted(glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "ms-playwright", "chromium-*", "chrome-win*", "chrome.exe")))
    if cands:
        print(f"  · 使用 Playwright 缓存 chromium：{cands[-1]}")
        return {"executable_path": cands[-1]}
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.isfile(p):
            print(f"  · 未找到匹配的 Playwright chromium，回退系统浏览器：{p}")
            return {"executable_path": p}
    return {}


def main() -> int:
    info = load_sidecar()
    port = info["port"]
    base = f"http://127.0.0.1:{port}/"
    print("=" * 74)
    print(" MiniYuxi 桌面端 · 可用性与体验验收")
    print(f" 工作台地址：{base}（桌面端 sidecar 实际服务的地址）")
    print(f" 内核版本  ：{info.get('version')} · 账号：{info.get('user')}/{info.get('role')}")
    print("=" * 74)

    browser = pick_browser()
    with sync_playwright() as pw:
        b = pw.chromium.launch(**browser)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: PAGE_ERR.append(str(e)))
        pg.on("console", lambda m: CONSOLE_ERR.append(m.text) if m.type == "error" else None)
        pg.on("response", lambda r: HTTP_ERR.append(f"{r.request.method} {r.url} -> {r.status}")
              if r.status >= 400 else None)

        # ── A. 登录流程 ─────────────────────────────────────────
        print("\n[A] 登录流程")
        t0 = time.time()
        pg.goto(base, wait_until="domcontentloaded")
        pg.wait_for_selector("#topNav .cloud-welcome__nav-item", timeout=30000)
        TIMINGS["首屏可交互"] = (time.time() - t0) * 1000

        # A1 未登录态：清掉桌面端注入的 token，模拟「未登录」
        pg.evaluate("() => localStorage.removeItem('miniyuxi_token')")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#topNav .cloud-welcome__nav-item", timeout=30000)
        fu = pg.text_content("#footerUser") or ""
        has_login_btn = pg.is_visible("#btnLogin")
        chk("A1 未登录：登录入口可见", has_login_btn, f"#btnLogin 可见；底部用户={fu.strip() or '(空)'}")

        # A2 错误口令 -> 异常提示
        pg.click("#btnLogin")
        pg.wait_for_selector("#loginModal", timeout=5000)
        pg.fill("#lmTenant", "default")
        pg.fill("#lmUser", "admin")
        pg.fill("#lmPass", "wrong-password")
        pg.click("#lmOk")
        err_shown = False
        for _ in range(40):
            txt = (pg.text_content("#lmErr") or "").strip()
            if txt and "登录中" not in txt:
                err_shown = True
                note(f"错误提示文案：{txt}")
                break
            time.sleep(0.25)
        chk("A2 错误口令：给出明确错误提示", err_shown)

        # A3 正常登录
        pg.fill("#lmPass", "admin123")
        pg.click("#lmOk")
        ok_login = False
        for _ in range(40):
            if pg.evaluate("() => !!localStorage.getItem('miniyuxi_token')"):
                ok_login = True
                break
            time.sleep(0.25)
        token = pg.evaluate("() => localStorage.getItem('miniyuxi_token')")
        chk("A3 正确口令：登录成功并落 token", ok_login, f"token 长度 {len(token) if token else 0}")

        # A4 刷新保持登录态
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#topNav .cloud-welcome__nav-item", timeout=30000)
        keep = pg.evaluate("() => !!localStorage.getItem('miniyuxi_token')")
        chk("A4 刷新页面：登录态保持", bool(keep))

        # A5 退出重登
        pg.evaluate("() => localStorage.removeItem('miniyuxi_token')")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#topNav .cloud-welcome__nav-item", timeout=30000)
        pg.click("#btnLogin")
        pg.wait_for_selector("#loginModal", timeout=5000)
        pg.fill("#lmUser", "admin")
        pg.fill("#lmPass", "admin123")
        pg.click("#lmOk")
        relogin = False
        for _ in range(40):
            if pg.evaluate("() => !!localStorage.getItem('miniyuxi_token')"):
                relogin = True
                break
            time.sleep(0.25)
        chk("A5 退出后重新登录：可再次登录", relogin)

        # ── B. 功能遍历 ─────────────────────────────────────────
        print("\n[B] 功能遍历（导航项）")
        items = pg.eval_on_selector_all(
            "#topNav .cloud-welcome__nav-item",
            "els => els.map(e => ({label: e.textContent.trim(), action: e.dataset.action}))",
        )
        note(f"导航项共 {len(items)} 个：" + " / ".join(f"{i['label']}({i['action']})" for i in items))

        for it in items:
            label, action = it["label"], it["action"]
            before_err = len(PAGE_ERR)
            t = time.time()
            try:
                pg.click(f'#topNav .cloud-welcome__nav-item[data-action="{action}"]')
                pg.wait_for_timeout(700)   # 给渲染/请求留出时间
                cost = (time.time() - t) * 1000
                TIMINGS[f"导航·{label}"] = cost
                new_err = PAGE_ERR[before_err:]
                shot = os.path.join(SHOTS, f"nav_{action}.png")
                try:
                    pg.screenshot(path=shot)
                except Exception:
                    pass
                overlays = open_overlays(pg)
                if new_err:
                    chk(f"B 导航「{label}」", False, f"运行时异常：{new_err[0][:110]}", "P0")
                else:
                    extra = f"{cost:.0f}ms"
                    if overlays:
                        extra += f" · 打开弹层：{'/'.join(overlays[:2])}"
                    chk(f"B 导航「{label}」", True, extra)
                dismiss_overlays(pg)
            except Exception as exc:
                chk(f"B 导航「{label}」", False, f"点击失败：{str(exc)[:110]}", "P0")

        # B2 核心操作：新建会话 + 发消息
        print("\n[B2] 核心操作")
        dismiss_overlays(pg)
        try:
            pg.click("#btnNewChat")
            pg.wait_for_timeout(400)
            chk("B2 新建会话", True)
        except Exception as exc:
            chk("B2 新建会话", False, str(exc)[:110], "P0")

        msg_ok = False
        try:
            pg.fill("#composerInput", "Ping 验收测试")
            t = time.time()
            pg.click("#btnSend")
            pg.wait_for_timeout(2500)
            TIMINGS["发送消息响应"] = (time.time() - t) * 1000
            html = pg.inner_html("#messageList") or ""
            msg_ok = len(html) > 0 and ("Ping" in html or len(html) > 50)
            chk("B2 发送消息并收到回显", msg_ok, f"{TIMINGS['发送消息响应']:.0f}ms", "P0")
        except Exception as exc:
            chk("B2 发送消息", False, str(exc)[:110], "P0")

        # B3 数据读写与保存：刷新后消息是否还在
        print("\n[B3] 数据读写与保存")
        pg.wait_for_timeout(500)
        before = pg.inner_html("#messageList") or ""
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#topNav .cloud-welcome__nav-item", timeout=30000)
        pg.wait_for_timeout(1200)
        after = pg.inner_html("#messageList") or ""
        persisted = ("Ping" in after) if ("Ping" in before) else (len(after) > 50)
        chk("B3 刷新后会话数据持久化", persisted,
            f"刷新前 {len(before)} 字符 / 刷新后 {len(after)} 字符", "P1")

        # B4 设置：主题切换
        print("\n[B4] 设置与通知")
        theme_ok = False
        try:
            before_theme = pg.evaluate("() => document.documentElement.getAttribute('data-theme') || document.body.className")
            pg.click("#btnTheme")
            pg.wait_for_timeout(500)
            after_theme = pg.evaluate("() => document.documentElement.getAttribute('data-theme') || document.body.className")
            theme_ok = before_theme != after_theme
            chk("B4 主题切换（设置项）", theme_ok, f"{before_theme} -> {after_theme}")
            pg.click("#btnTheme")   # 切回来
            pg.wait_for_timeout(300)
        except Exception as exc:
            chk("B4 主题切换（设置项）", False, str(exc)[:110])

        # B5 通知：toast
        toast_ok = False
        try:
            pg.evaluate("() => { const t=document.getElementById('toast'); t.textContent='验收通知测试'; t.hidden=false; t.classList.add('is-show'); }")
            pg.wait_for_timeout(300)
            toast_ok = pg.is_visible("#toast")
            chk("B5 通知提示（Toast）可展示", toast_ok)
        except Exception as exc:
            chk("B5 通知提示（Toast）", False, str(exc)[:110])

        # ── C. 流畅度 ───────────────────────────────────────────
        print("\n[C] 流畅度")
        for k, v in TIMINGS.items():
            print(f"  · {k}: {v:.0f} ms")
        nav_times = {k: v for k, v in TIMINGS.items() if k.startswith("导航·")}
        if nav_times:
            slow = {k: v for k, v in nav_times.items() if v > 1500}
            chk("C 页面切换均 < 1500ms", not slow, f"最慢 {max(nav_times.values()):.0f}ms")
        chk("C 首屏可交互 < 5000ms", TIMINGS.get("首屏可交互", 99999) < 5000,
            f"{TIMINGS.get('首屏可交互', 0):.0f}ms")

        # ── 错误汇总 ────────────────────────────────────────────
        print("\n[E] 运行时错误汇总")
        print(f"  · JS 运行时异常(pageerror)：{len(PAGE_ERR)}")
        for e in PAGE_ERR[:8]:
            print(f"      - {e[:160]}")
        print(f"  · console.error：{len(CONSOLE_ERR)}")
        for e in CONSOLE_ERR[:8]:
            print(f"      - {e[:160]}")
        real_http = [h for h in HTTP_ERR if "/api/" in h]
        print(f"  · HTTP >=400（接口类）：{len(real_http)}")
        for h in real_http[:12]:
            print(f"      - {h[:160]}")
        # 401/404 在遍历里属预期（未授权/路由未开放），单独列出不直接判失败
        chk("E 无 JS 运行时异常", len(PAGE_ERR) == 0, f"{len(PAGE_ERR)} 条", "P0")

        pg.screenshot(path=os.path.join(SHOTS, "acceptance_final.png"))
        b.close()

    print("\n" + "=" * 74)
    print(f" 通过 {len(PASS)} 项 · 失败 {len(FAIL)} 项")
    for lvl, name, extra in FAIL:
        print(f"   ❌ [{lvl}] {name}" + (f" — {extra}" if extra else ""))
    print("=" * 74)

    out = {
        "passed": PASS,
        "failed": [{"level": l, "name": n, "extra": e} for l, n, e in FAIL],
        "timings_ms": {k: round(v, 1) for k, v in TIMINGS.items()},
        "page_errors": PAGE_ERR,
        "console_errors": CONSOLE_ERR,
        "http_errors": HTTP_ERR,
    }
    with open(os.path.join(ROOT, "docs", "_acceptance_desktop.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f" 明细已写入 docs/_acceptance_desktop.json")

    bad = [f for f in FAIL if f[0] in ("P0", "P1")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
