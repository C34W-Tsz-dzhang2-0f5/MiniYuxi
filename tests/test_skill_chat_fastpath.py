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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import rag  # noqa: E402
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
