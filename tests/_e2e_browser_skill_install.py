"""真实浏览器回归（playwright + chromium）：技能安装/卸载走真实 UI 路径。

覆盖真实用户路径（不是 HTTP 级 e2e）：
  打开首页 → 点登录 → 填账号密码 → 打开左侧工具菜单 → 点「技能」→
  打开「＋ 安装 / 管理技能」→ 粘贴 SKILL.md → 点安装 → 断言已装列表出现该技能 →
  点卸载（确认弹窗）→ 断言列表移除。

自包含：脚本自己起 run.py（隔离 data 目录 + 隔离 skills 目录）、跑完自己清理并杀进程。
截图落在 docs/_shots/（.gitignore 忽略 *.png，不入库）。

运行：
    .venv/Scripts/python.exe tests/_e2e_browser_skill_install.py
前置：playwright + chromium 已安装（`python -m playwright install chromium`）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = 8801
BASE = f"http://127.0.0.1:{PORT}"
SKILL_NAME = "e2e-demo-skill"
SHOTS = os.path.join(ROOT, "docs", "_shots")

SKILL_MD = (
    "---\n"
    f"name: {SKILL_NAME}\n"
    "description: E2E 真实浏览器回归用的一次性演示技能（跑完即卸载）\n"
    "---\n"
    "当用户要求演示时，输出一行：这是 E2E 演示技能。\n"
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


def wait_health(timeout: float = 40.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    from playwright.sync_api import sync_playwright

    data_dir = tempfile.mkdtemp(prefix="my_e2e_data_")
    skills_dir = tempfile.mkdtemp(prefix="my_e2e_skills_")
    os.makedirs(SHOTS, exist_ok=True)
    venv_py = sys.executable

    env = dict(os.environ)
    env["MINIYUXI_DATA_DIR"] = data_dir
    # 让被起的内核用隔离的 skills 目录（skills_catalog.SKILLS_DIR 可由环境变量覆盖时生效；
    # 若内核不支持则回落到仓库 skills/，脚本结束会清理同名技能）
    env["MINIYUXI_SKILLS_DIR"] = skills_dir

    proc = subprocess.Popen([venv_py, "run.py"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        check("服务启动 /api/health", wait_health(), BASE)
        if not results[-1][1]:
            return 1

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("dialog", lambda d: d.accept())

            page.goto(BASE, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(SHOTS, "e2e-01-home.png"))
            check("首页加载", page.locator("body").count() == 1)

            # ---- 登录（真实弹窗）----
            # 首页欢迎区顶部导航会盖住登录按钮 → 用真实 click 事件触发（仍走真实 handler）
            page.evaluate("() => { var b = document.getElementById('btnLogin'); if (b) b.click(); }")
            page.wait_for_selector("#loginModal:not([hidden])", timeout=8000)
            page.fill("#lmTenant", "default")
            page.fill("#lmUser", "admin")
            page.fill("#lmPass", "admin123")
            page.screenshot(path=os.path.join(SHOTS, "e2e-02-login.png"))
            page.click("#lmOk", force=True)
            page.wait_for_timeout(2500)
            page.screenshot(path=os.path.join(SHOTS, "e2e-03-loggedin.png"))
            token = page.evaluate("() => { try { return localStorage.getItem('miniyuxi_token') || ''; } catch(e){ return ''; } }")
            check("登录成功（拿到 token）", bool(token), (token[:12] + "…") if token else "无 token")

            # ---- 打开工具菜单 → 技能 ----
            page.click("#btnToolMenu", force=True)
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(SHOTS, "e2e-04-toolmenu.png"))
            page.click("#toolMenu .tool-menu__item:has-text('技能')", force=True)
            page.wait_for_timeout(900)
            page.wait_for_selector("#skillInstallBtn", timeout=15000)
            page.screenshot(path=os.path.join(SHOTS, "e2e-05-skilldrawer.png"))
            check("技能抽屉打开（有安装入口）", page.locator("#skillInstallBtn").count() == 1)

            # ---- 打开安装弹窗 → 粘贴安装 ----
            page.wait_for_selector("#skillInstallBtn", timeout=15000)
            page.evaluate("() => document.getElementById('skillInstallBtn').click()")
            page.wait_for_selector("#siPaste", timeout=8000)
            page.fill("#siPaste", SKILL_MD)
            page.fill("#siNamePaste", SKILL_NAME)
            page.screenshot(path=os.path.join(SHOTS, "e2e-06-installform.png"))
            page.evaluate("() => { var b = document.getElementById('siInstall'); if (b) b.click(); }")
            page.wait_for_timeout(3000)
            page.screenshot(path=os.path.join(SHOTS, "e2e-07-afterinstall.png"))

            # 重开安装弹窗看「已安装」列表
            page.wait_for_selector("#skillInstallBtn", timeout=15000)
            page.evaluate("() => document.getElementById('skillInstallBtn').click()")
            page.wait_for_selector("#siList", timeout=8000)
            page.wait_for_timeout(2000)
            page.screenshot(path=os.path.join(SHOTS, "e2e-08-installedlist.png"))
            names = page.locator("#siList .si-name").all_inner_texts()
            check("安装后出现在已装列表", SKILL_NAME in names, "共 " + str(len(names)) + " 个技能")

            # ---- 卸载（confirm 覆写为恒真，避免原生对话框卡住）----
            if SKILL_NAME in names:
                page.evaluate("() => { window.confirm = function () { return true; }; }")
                page.wait_for_selector(f"#siList .si-del[data-name='{SKILL_NAME}']", timeout=8000)
                page.evaluate(
                    "() => { var b = document.querySelector(\"#siList .si-del[data-name='"
                    + SKILL_NAME + "']\"); if (b) b.click(); }")
                page.wait_for_timeout(3500)
                page.screenshot(path=os.path.join(SHOTS, "e2e-09-afteruninstall.png"))
                disk_gone = not os.path.isdir(os.path.join(ROOT, "skills", SKILL_NAME))
                check("卸载后磁盘目录已删除", disk_gone, os.path.join("skills", SKILL_NAME))
                # 重开看列表
                page.wait_for_selector("#skillInstallBtn", timeout=15000)
                page.evaluate("() => document.getElementById('skillInstallBtn').click()")
                page.wait_for_selector("#siList", timeout=8000)
                page.wait_for_timeout(1800)
                names2 = page.locator("#siList .si-name").all_inner_texts()
                check("卸载后从已装列表移除", SKILL_NAME not in names2, "剩余 " + str(len(names2)) + " 个技能")

            browser.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(skills_dir, ignore_errors=True)
        # 兜底清理：若内核回落到仓库 skills/，删掉本次演示技能
        leftover = os.path.join(ROOT, "skills", SKILL_NAME)
        if os.path.isdir(leftover):
            shutil.rmtree(leftover, ignore_errors=True)
            print(f"  · 兜底清理残留 {leftover}")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n==== 真实浏览器回归：PASS={passed}  FAIL={failed} ====")
    print("ALL_PASS" if failed == 0 else "HAS_FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
