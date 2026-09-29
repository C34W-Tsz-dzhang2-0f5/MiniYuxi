"""技能安装 + 视频生成 能力验证（自包含，无需启动服务）。

覆盖：
  T6 技能安装（core/skills_install.py）：
    - 纯函数 safe_skill_name / name_from_frontmatter / normalize_url
    - 粘贴安装（paste）→ 写 SKILL.md + 校验 frontmatter + catalog 可见 → 卸载
    - 本地路径安装（path）
    - 显式 name 覆盖：回写 frontmatter
    - 嵌套技能集合仓库（根无 SKILL.md，如 github.com/mattpocock/skills）：
        · 显式 name：count=2 + 按名卸载只删对应子目录、不连带误删
        · **无显式 name**（回归：旧版会 UnboundLocalError → 500）
        · 卸载后 catalog 立即刷新（回归：旧版 mtime 缓存导致列表不更新）
    - 校验：缺 name → 400；http:// → 400；非仓库/zip 的 https → 400；越界 name → 400
  视频生成（core/tools_registry.py，@tool 注册）：
    - 未配置视频连接器 → 明确"未配置"指引（不崩）
    - 缺 prompt → error；已配置（mock MCP）→ 正确转发
    - video.generate 已在 list_tools() 注册

运行：
  .venv/Scripts/python.exe tests/_verify_skill_install_and_video.py
"""
import json
import os
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import skills_catalog  # noqa: E402
from core.skills_install import (  # noqa: E402
    install_skill, uninstall_skill, safe_skill_name, name_from_frontmatter,
    normalize_url, SkillInstallError,
)
import core.tools_registry as tr  # noqa: E402
import core.connectors as connectors_mod  # noqa: E402
import core.mcp_client as mcp_mod  # noqa: E402

PASS = 0
FAIL = 0
_msgs = []


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        _msgs.append("  PASS  " + label)
    else:
        FAIL += 1
        _msgs.append("  FAIL  " + label)


def _with_temp_skills_dir(fn):
    """把 skills_catalog.SKILLS_DIR 临时指向空目录（安装校验走 catalog，需一致）。"""
    orig = skills_catalog.SKILLS_DIR
    tmp = tempfile.mkdtemp(prefix="my_skills_")
    skills_catalog.SKILLS_DIR = tmp
    skills_catalog.invalidate_cache()
    try:
        return fn(tmp)
    finally:
        skills_catalog.SKILLS_DIR = orig
        skills_catalog.invalidate_cache()
        shutil.rmtree(tmp, ignore_errors=True)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ----------------------------------------------------------------------------
# 1) 纯函数
# ----------------------------------------------------------------------------
def test_pure_helpers():
    check(safe_skill_name("abc-1.2_X") == "abc-1.2_X", "safe_skill_name 合法名放行")
    check(safe_skill_name("../evil") is None, "safe_skill_name 拒绝 ..")
    check(safe_skill_name("a/b") is None, "safe_skill_name 拒绝 /")
    check(safe_skill_name("a\\b") is None, "safe_skill_name 拒绝 \\")
    check(safe_skill_name("") is None, "safe_skill_name 拒绝空串")
    check(safe_skill_name("x" * 100) == ("x" * 64), "safe_skill_name 截断到 64")
    check(name_from_frontmatter("---\nname: foo\ndescription: x\n---") == "foo",
          "name_from_frontmatter 解析 name")
    check(name_from_frontmatter("no frontmatter") is None, "name_from_frontmatter 缺失返回 None")
    # URL 归一
    check(normalize_url("github.com/mattpocock/skills") == "https://github.com/mattpocock/skills.git",
          "normalize_url 补 https + .git（用户原样输入）")
    check(normalize_url("https://github.com/o/r") == "https://github.com/o/r.git",
          "normalize_url 仓库页补 .git")
    check(normalize_url("https://x.com/a.zip").endswith(".zip"), "normalize_url 放行 .zip")
    for bad in ("http://github.com/o/r", "ftp://x/y", "just-text"):
        try:
            normalize_url(bad)
            check(False, "normalize_url 应拒绝 %s" % bad)
        except SkillInstallError:
            check(True, "normalize_url 拒绝 %s" % bad)


# ----------------------------------------------------------------------------
# 2) 粘贴安装 + catalog 可见 + 卸载
# ----------------------------------------------------------------------------
def test_paste_install_and_uninstall():
    def run(tmp):
        res = install_skill("paste", "---\nname: demo_skill\ndescription: 演示技能\n---\n正文", "")
        check(res.get("ok") is True, "paste 安装返回 ok")
        check(res.get("name") == "demo_skill", "paste 安装解析出 name")
        check(os.path.isfile(os.path.join(tmp, "demo_skill", "SKILL.md")), "SKILL.md 已写入")
        check(skills_catalog.load_skill("demo_skill") is not None, "catalog 可加载该技能")
        check(uninstall_skill("demo_skill").get("ok") is True, "卸载返回 ok")
        check(not os.path.isdir(os.path.join(tmp, "demo_skill")), "卸载后目录已删除")
    _with_temp_skills_dir(run)


# ----------------------------------------------------------------------------
# 3) 本地路径安装
# ----------------------------------------------------------------------------
def test_path_install():
    def run(tmp):
        src = tempfile.mkdtemp(prefix="src_skill_")
        try:
            _write(os.path.join(src, "SKILL.md"), "---\nname: path_skill\ndescription: 本地路径\n---\nbody")
            res = install_skill("path", src, "")
            check(res.get("ok") is True and res.get("name") == "path_skill", "path 安装成功")
            check(os.path.isfile(os.path.join(tmp, "path_skill", "SKILL.md")), "path 复制了 SKILL.md")
            uninstall_skill("path_skill")
        finally:
            shutil.rmtree(src, ignore_errors=True)
    _with_temp_skills_dir(run)


# ----------------------------------------------------------------------------
# 4) 显式 name 覆盖
# ----------------------------------------------------------------------------
def test_explicit_name_override():
    def run(tmp):
        res = install_skill("paste", "---\nname: orig_name\ndescription: 改写测试\n---\nbody", "over_name")
        check(res.get("name") == "over_name", "显式 name 覆盖 frontmatter name")
        tp = os.path.join(tmp, "over_name", "SKILL.md")
        check(os.path.isfile(tp), "目录以显式 name 命名")
        txt = open(tp, encoding="utf-8").read()
        check("name: over_name" in txt and "name: orig_name" not in txt, "frontmatter 已回写")
        uninstall_skill("over_name")
    _with_temp_skills_dir(run)


# ----------------------------------------------------------------------------
# 5) 嵌套技能集合仓库
# ----------------------------------------------------------------------------
def _make_collection():
    src = tempfile.mkdtemp(prefix="coll_")
    _write(os.path.join(src, "engineering", "tdd", "SKILL.md"),
           "---\nname: tdd\ndescription: 测试驱动开发\n---\nbody")
    _write(os.path.join(src, "productivity", "grill-me", "SKILL.md"),
           "---\nname: grill-me\ndescription: 追问式设计\n---\nbody")
    return src


def test_nested_with_explicit_name():
    def run(tmp):
        src = _make_collection()
        try:
            res = install_skill("path", src, "mattpocock-skills")
            check(res.get("ok") is True, "嵌套集合安装成功（显式 name）")
            check(res.get("count") == 2, "递归发现 2 个嵌套技能")
            check(skills_catalog.load_skill("tdd") is not None, "catalog 可见 tdd")
            ur = uninstall_skill("tdd")
            check(ur.get("removed") is True, "卸载 tdd 命中")
            check(skills_catalog.load_skill("tdd") is None, "tdd 已移除")
            check(skills_catalog.load_skill("grill-me") is not None, "grill-me 仍在（无连带误删）")
            uninstall_skill("grill-me")
        finally:
            shutil.rmtree(src, ignore_errors=True)
    _with_temp_skills_dir(run)


def test_nested_without_explicit_name():
    """回归：旧版 `name = explicit or name` 在无显式名时会 UnboundLocalError → HTTP 500。"""
    def run(tmp):
        src = _make_collection()
        try:
            res = install_skill("path", src, "")   # 不传 name
            check(res.get("ok") is True, "嵌套集合安装成功（无显式 name，不崩）")
            check(res.get("count") == 2, "无显式 name 仍发现 2 个技能")
            check(os.path.isdir(res.get("path")), "容器目录已创建")
            uninstall_skill("tdd")
            uninstall_skill("grill-me")
        finally:
            shutil.rmtree(src, ignore_errors=True)
    _with_temp_skills_dir(run)


def test_uninstall_refreshes_catalog():
    """回归：嵌套卸载只改子目录 mtime，旧版缓存导致 /api/skills/list 不更新。"""
    def run(tmp):
        src = _make_collection()
        try:
            install_skill("path", src, "coll")
            before = {s["name"] for s in skills_catalog.list_skills()}
            check("tdd" in before, "卸载前列表含 tdd")
            uninstall_skill("tdd")
            after = {s["name"] for s in skills_catalog.list_skills()}
            check("tdd" not in after, "卸载后列表立即不含 tdd（缓存已刷新）")
            check("grill-me" in after, "同仓库其它技能不受影响")
        finally:
            shutil.rmtree(src, ignore_errors=True)
    _with_temp_skills_dir(run)


# ----------------------------------------------------------------------------
# 6) 安全校验：各类非法输入 → SkillInstallError
# ----------------------------------------------------------------------------
def test_validation_errors():
    def run(tmp):
        cases = [
            ("paste 缺 name/frontmatter", lambda: install_skill("paste", "随便写点", "")),
            ("非 https", lambda: install_skill("url", "http://x.com/a.zip", "")),
            ("非仓库/zip 的 https", lambda: install_skill("url", "https://example.com/readme", "")),
            ("越界 name 卸载", lambda: uninstall_skill("../escape")),
            ("未知安装方式", lambda: install_skill("magic", "x", "")),
        ]
        for label, fn in cases:
            try:
                fn()
                check(False, "%s 应报错" % label)
            except SkillInstallError:
                check(True, "%s → SkillInstallError" % label)
    _with_temp_skills_dir(run)


# ----------------------------------------------------------------------------
# 7) 视频生成
# ----------------------------------------------------------------------------
def _patch_connectors(fake_list, fake_mcp):
    saved = (connectors_mod.list_connectors, mcp_mod._resolve_token, mcp_mod.MCPClientSSE)
    connectors_mod.list_connectors = fake_list
    mcp_mod._resolve_token = lambda cfg: None
    mcp_mod.MCPClientSSE = fake_mcp
    return saved


def _restore_connectors(saved):
    (connectors_mod.list_connectors, mcp_mod._resolve_token, mcp_mod.MCPClientSSE) = saved


def test_video_no_connector():
    saved = _patch_connectors(lambda: [], None)
    try:
        out = tr._video_generate(tenant_id=None, prompt="一只猫在跳舞")
        check(isinstance(out, dict) and "error" in out, "无连接器返回 error 字典")
        check("未配置" in out.get("error", ""), "无连接器提示'未配置视频服务商'")
    finally:
        _restore_connectors(saved)


def test_video_missing_prompt():
    saved = _patch_connectors(lambda: [], None)
    try:
        out = tr._video_generate(tenant_id=None)
        check(isinstance(out, dict) and "error" in out, "缺 prompt 返回 error")
    finally:
        _restore_connectors(saved)


def test_video_forward():
    class FakeSSE:
        def __init__(self, endpoint, token=None, timeout=None):
            self.endpoint = endpoint

        def initialize(self):
            pass

        def list_tools(self):
            return [{"name": "make_video", "description": "text to video"}]

        def call_tool(self, name, payload):
            return {"ok": True, "tool": name, "got": payload.get("prompt")}

        def close(self):
            pass

    cfg = {"capability": "video", "endpoint": "http://fake-mcp", "video_tool": "make_video"}
    saved = _patch_connectors(
        lambda: [{"id": "fake-video", "kind": "mcp", "enabled": True, "config_json": json.dumps(cfg)}],
        FakeSSE,
    )
    try:
        out = tr._video_generate(tenant_id=None, prompt="日落地平线")
        check(out.get("ok") is True, "已配置连接器 → 转发成功")
        check(out.get("tool") == "make_video", "调用了正确的视频工具")
        check(out.get("got") == "日落地平线", "prompt 正确透传")
    finally:
        _restore_connectors(saved)


def test_video_registered():
    names = [t.get("name") for t in tr.list_tools()]
    check("video.generate" in names, "video.generate 已注册（@tool）")


def main():
    test_pure_helpers()
    test_paste_install_and_uninstall()
    test_path_install()
    test_explicit_name_override()
    test_nested_with_explicit_name()
    test_nested_without_explicit_name()
    test_uninstall_refreshes_catalog()
    test_validation_errors()
    test_video_no_connector()
    test_video_missing_prompt()
    test_video_forward()
    test_video_registered()

    print("\n".join(_msgs))
    print("\n==== 技能安装 / 视频生成 验证：PASS=%d  FAIL=%d ====" % (PASS, FAIL))
    if FAIL:
        sys.exit(1)
    print("ALL_PASS")


if __name__ == "__main__":
    main()
