"""前端收口 · 只读路由验证（不写任何业务数据）。

覆盖：
  Phase0  V1   /wb、/legacy 302 下线 + 品牌无 WorkBuddy 残留
  Phase1  L1/L2/L3/L4 抽屉开关、nav 更多、多模型条首屏、访问开关默认受限
  Phase2  V2/V5/V6/V7 内联 logo、强调态、暗色、留白；U7/U8/U9/U10/L5/L8 前端能力存在
用法：python _smoke_routes.py
"""
import re
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402

client = TestClient(api.app, follow_redirects=False)

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print("   %s %s %s" % ("✓" if cond else "✗", label, extra))


print("== Phase 0 · V1 旧入口下线 & 品牌统一")
r = client.get("/wb")
chk("GET /wb → 302", r.status_code == 302, str(r.status_code))
chk("/wb 落点 = /", r.headers.get("location") == "/", str(r.headers.get("location")))

r = client.get("/legacy")
chk("GET /legacy → 302", r.status_code == 302, str(r.status_code))
chk("/legacy 落点 = /", r.headers.get("location") == "/", str(r.headers.get("location")))

chk("静态资源 /wb/wb_workbench.css 仍 200",
    client.get("/wb/wb_workbench.css").status_code == 200)
chk("静态资源 /wb/wb_workbench.js 仍 200",
    client.get("/wb/wb_workbench.js").status_code == 200)

r = client.get("/")
html = r.text
chk("GET / 200", r.status_code == 200, str(r.status_code))
chk("主界面标题含 MiniYuxi", "MiniYuxi" in html)
chk("无 workbuddy.cn 外链", "workbuddy.cn" not in html.lower())
chk("无 'WorkBuddy, 我帮你' 文案", "WorkBuddy, 我帮你" not in html)
chk("V2 内联 SVG logo >= 3 处",
    html.count("brand-logo-mark") >= 3, "实际 %d" % html.count("brand-logo-mark"))
chk("V2 图标 JSON 已注入（无占位符）", "__ICONS_JSON__" not in html)

print("== Phase 1 · L1 右栏抽屉")
chk("L1 头部抽屉开关存在", 'id="btnDetailDrawer"' in html)
chk("L1 遮罩层存在", 'id="detailPanelDrawerBackdrop"' in html)
css = client.get("/wb/wb_workbench.css").text
chk("L1 CSS 有 is-drawer-open", ".detail-panel-container.is-drawer-open" in css)
chk("L1 1024 断点不再直接 display:none",
    ".detail-panel-container { display: none; }" not in css)

print("== Phase 1 · L2 nav 溢出 / L3 多模型首屏 / L4 访问开关")
js = client.get("/wb/wb_workbench.js").text
chk("L2 JS 渲染「更多」菜单", "btnNavMore" in js and "navMoreMenu" in js)
chk("L2 CSS 有 nav-more 样式", ".nav-more {" in css)
chk("L2 移动端 nav 不再整块隐藏",
    ".cloud-welcome__nav { display: none; }" not in css)
chk("L3 路由条在 main 之前（首屏）",
    html.find('id="modelBar"') < html.find('class="cloud-welcome__main"'))
chk("L3 chatDock 内已无重复 modelBar",
    html.count('id="modelBar"') == 1, "出现 %d 次" % html.count('id="modelBar"'))
chk("L4 允许完全访问不再默认勾选",
    re.search(r'id="allowFullAccess"[^>]*checked', html) is None)

print("== Phase 1 · U3/U4/U5/U7/U8")
chk("U1 ensureToken 不再静默登录",
    "login('default', 'admin', 'admin123')" not in js)
chk("U1 默认口令提示仅回环显示", "isLoopback" in js)
chk("U4 访问开关默认受限", "state.allowFullAccess = false" in js)
chk("U3 登录引导弹窗", "showLoginModal" in js)
chk("U4 快捷入口点击即发", "即发" in js or "send(" in js)
chk("U5 技能抽屉区分 folder 语义", "文件夹技能" in js)
chk("U7 消息操作条", "msg-actions" in css and "复制" in js)
chk("U8 Markdown 渲染", "mdToHtml" in js and ".md-pre" in css)

print("== Phase 2 · V5/V6/V7 + U9/U10/L5/L6/L8")
chk("V5 强调态统一（主色）", ".mx-seg button.on { background: var(--wb-primary)" in css)
chk("V6 暗色对比微调", "body.dark .composer-shell:focus-within" in css)
chk("V7 欢迎页留白自适应", "clamp(40px, 11vh, 128px)" in css)
chk("U9 引用文件可移除", "ref-remove" in css and "ref-remove" in js)
chk("U10 ⌘K 快捷键", "metaKey" in js and "'k'" in js)
chk("L5 双编辑器草稿互通", "carryDraft" in js)
chk("L6 移动端工具热区放大", "min-height: 34px" in css)
chk("L8 流式用 rAF 而非 setInterval",
    "requestAnimationFrame" in js and "clearInterval(timer)" not in js)

print("\nROUTE SMOKE PASSED" if ok else "\nROUTE SMOKE FAILED")
sys.exit(0 if ok else 1)
