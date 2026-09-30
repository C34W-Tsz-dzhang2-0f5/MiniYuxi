# -*- coding: utf-8 -*-
"""「指定模型/自动路由」也能装技能 + git clone 镜像兜底（2026-09-30 阿长截图回归）。

背景：阿长在「指定模型 deepseek:deepseek-chat」下粘贴
  `npx skills add https://github.com/vercel-labs/skills --skill find-skills`
模型只是把命令"解释"了一遍，没有执行。根因有两层：
  1. /api/models/chat（指定模型/自动路由）是纯对话，不带工具；skill.install
     快路径只接在工作台 /api/chat（rag.answer）那条链上；
  2. 即使走到执行，本机直连 github.com clone 大概率超时，skills_install 没有镜像兜底。

本文件锁四件事：
  1. rag._detect_tool 必须确定性识别截图里的原命令（--skill → select）；
  2. api.models_chat 必须接上 rag._detect_tool/_run_tool 快路径（源码级锁定）；
  3. git clone 直连失败后自动改走镜像（MINIYUXI_GIT_MIRROR，默认 ghfast.top）并成功；
  4. 直连+镜像都失败时，报错必须同时带两边信息（可诊断，不裸抛栈）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import rag  # noqa: E402
from core import skills_catalog  # noqa: E402
from core import skills_install as si  # noqa: E402


# ------------------------------------------------ 1. 命令识别（截图原命令）

def test_detect_tool_parses_screenshot_command():
    det = rag._detect_tool(
        "npx skills add https://github.com/vercel-labs/skills --skill find-skills")
    assert det is not None, "截图里的原命令必须被识别为工具指令"
    name, args = det
    assert name == "skill.install"
    assert args["source"] == "https://github.com/vercel-labs/skills"
    assert args["select"] == "find-skills"


def test_detect_tool_ignores_plain_question():
    assert rag._detect_tool("带薪年休假怎么算") is None


# ------------------------------------------------ 2. 指定模型链路接线锁定

def test_models_chat_wires_tool_fastpath():
    """🔴 核心回归：/api/models/chat 必须在调 LLM 之前先过工具快路径。"""
    import inspect
    import api
    src = inspect.getsource(api.models_chat)
    assert "rag._detect_tool" in src, "指定模型/自动路由必须复用 rag 的确定性工具识别"
    assert "rag._run_tool" in src, "命中后必须直接执行工具，而不是交给模型解释"


# ------------------------------------------------ 3. git clone 镜像兜底

def _make_fixture(tmp_path):
    repo = tmp_path / "_fixture_repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text(
        "---\nname: mirror-demo\ndescription: 镜像兜底测试技能\n---\n\n# body\n",
        encoding="utf-8")
    return repo


def test_clone_falls_back_to_mirror(monkeypatch, tmp_path):
    repo = _make_fixture(tmp_path)
    calls = []

    def fake_run(cmd, timeout, capture_output, check):
        calls.append(list(cmd))
        if len(calls) == 1:          # 第一次（直连）失败
            raise subprocess.CalledProcessError(128, cmd, stderr=b"fatal: unable to access")
        # cmd = ["git","clone","--depth","1",<url>,<stage>] → stage 是最后一个参数
        shutil.copytree(repo, cmd[-1], dirs_exist_ok=True)  # 第二次（镜像）假装 clone 成功
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.delenv("MINIYUXI_GIT_MIRROR", raising=False)
    monkeypatch.setattr(si.subprocess, "run", fake_run)

    skills_dir = tmp_path / "skills"
    res = si.install_skill("url", "https://github.com/foo/bar.git", skills_dir=str(skills_dir))
    assert res["ok"] is True and res["name"] == "mirror-demo"
    assert len(calls) == 2, "直连失败后必须恰好重试一次镜像"
    assert calls[0][4] == "https://github.com/foo/bar.git"
    assert calls[1][4] == "https://ghfast.top/https://github.com/foo/bar.git"
    assert (skills_dir / "mirror-demo" / "SKILL.md").is_file()


def test_clone_error_reports_both_attempts(monkeypatch, tmp_path):
    def fake_run(cmd, timeout, capture_output, check):
        raise subprocess.CalledProcessError(128, cmd, stderr=b"boom")

    monkeypatch.delenv("MINIYUXI_GIT_MIRROR", raising=False)
    monkeypatch.setattr(si.subprocess, "run", fake_run)

    with pytest.raises(si.SkillInstallError) as ei:
        si.install_skill("url", "https://github.com/foo/bar.git",
                         skills_dir=str(tmp_path / "skills2"))
    msg = str(ei.value)
    assert "直连" in msg and "ghfast.top" in msg and "boom" in msg, \
        "失败信息必须同时带直连与镜像两侧错误，便于诊断"


# ------------------------------------------------ 4. 本机无 git → zip 兜底
# 2026-09-30 阿长第二张截图：双击 bat 起的服务进程 PATH 里没有 git，
# 报「本机未安装 git」。现在改为：找不到 git 时自动走 GitHub archive zip。

def test_no_git_falls_back_to_zip(monkeypatch, tmp_path):
    """🔴 核心回归：_find_git 找不到 git 时，必须改走 archive zip 而非直接失败。"""
    urls = []

    def fake_fetch(zip_url, stage):
        urls.append(zip_url)
        # 模拟 GitHub archive zip：带顶层目录 bar-main/
        top = os.path.join(stage, "bar-main")
        os.makedirs(top)
        with open(os.path.join(top, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: mirror-demo\ndescription: 无git兜底\n---\n\n# body\n")

    monkeypatch.delenv("MINIYUXI_GIT_MIRROR", raising=False)
    monkeypatch.setattr(si, "_find_git", lambda: None)
    monkeypatch.setattr(si, "_fetch_zip_into", fake_fetch)

    skills_dir = tmp_path / "skills3"
    res = si.install_skill("url", "https://github.com/foo/bar.git", skills_dir=str(skills_dir))
    assert res["ok"] is True and res["name"] == "mirror-demo"
    # 第一个候选必须是「镜像 + main 分支」的 archive zip
    assert urls[0] == "https://ghfast.top/https://github.com/foo/bar/archive/refs/heads/main.zip", \
        "无 git 时首个兜底候选应为 ghfast.top 镜像的 main.zip"
    # archive zip 的顶层目录 bar-main/ 必须被塌缩掉
    assert (skills_dir / "mirror-demo" / "SKILL.md").is_file()


def test_no_git_zip_all_fail_reports_diagnosable(monkeypatch, tmp_path):
    def fake_fetch(zip_url, stage):
        raise si.SkillInstallError("下载失败：超时 " + zip_url[-20:])

    monkeypatch.delenv("MINIYUXI_GIT_MIRROR", raising=False)
    monkeypatch.setattr(si, "_find_git", lambda: None)
    monkeypatch.setattr(si, "_fetch_zip_into", fake_fetch)

    with pytest.raises(si.SkillInstallError) as ei:
        si.install_skill("url", "https://github.com/foo/bar.git",
                         skills_dir=str(tmp_path / "skills4"))
    msg = str(ei.value)
    assert "zip 兜底" in msg and "main/master" in msg and "下载失败" in msg, \
        "zip 兜底全失败时报错必须说明尝试范围与原因"


def test_tool_result_formatted_not_raw_dict():
    """🔴 回归（2026-09-30 阿长截图）：skill.install 成功却把原始 dict 怼进对话，
    看起来像报错。必须格式化为人类可读文案（原始结构仍留在 tool_result 供程序用）。"""
    r = {"name": "skill.install",
         "result": {"ok": True, "name": "find-skills", "path": "X:\skills\find-skills",
                    "description": "Helps users discover skills", "count": 1,
                    "note": "已安装并刷新技能目录"}}
    text = rag._fmt_tool_text("skill.install", r)
    assert "✅" in text and "技能安装成功" in text and "find-skills" in text
    assert "{'ok'" not in text and "'ok': True" not in text, "不得把原始 dict 暴露给用户"
    err = rag._fmt_tool_text("skill.install", {"error": "技能安装失败：boom"})
    assert "❌" in err and "boom" in err


def test_inject_text_covers_beyond_first_8_skills():
    """🔴 回归（2026-09-30）：inject_text 默认 limit=8，本机已装 48 个技能时
    新装的技能（字母序第 13）永远不进提示词，用户感知「装完没反应」。默认值必须 ≥48。"""
    import inspect
    sig = inspect.signature(skills_catalog.inject_text)
    assert sig.parameters["limit"].default >= 48, \
        "inject_text 默认 limit 过小，新装技能会被截掉"
