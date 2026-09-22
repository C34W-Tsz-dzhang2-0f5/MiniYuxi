"""Hermes 源码解读系列 → MiniYuxi 落地测试。

验证本次落地的三块（对应 Hermes 三/十/十一）：
  B-5 安全分层：hardline_block / is_dangerous_command / validate_within_dir / validate_script
  B-1 工具治理：toolset 过滤 + run_tool_governed 审批门 + hardline 兜底
  B-4 Cron=Agent 任务：_run_job 通用分发（agent / script / 未知 kind fail-closed）

不依赖外部模型/网络/DB：用 monkeypatch 隔离副作用，跑得快且离线稳定。
"""
import os
import sys
import types

import pytest

# ---------- B-5 安全分层 ----------
from core import security


def test_hardline_block_hits():
    assert security.hardline_block("rm -rf /")
    assert security.hardline_block("sudo rm -rf --no-preserve-root /")
    assert security.hardline_block("mkfs.ext4 /dev/sda1")
    assert security.hardline_block("dd if=/dev/zero of=/dev/sda")
    assert security.hardline_block("shutdown -h now")
    assert security.hardline_block(":(){ :|:& };:")


def test_hardline_block_safe():
    assert not security.hardline_block("")
    assert not security.hardline_block("ls -la /tmp")
    assert not security.hardline_block("rm -rf ./build")  # 非根目录，非 hardline


def test_is_dangerous_command():
    assert security.is_dangerous_command("sudo reboot")
    assert security.is_dangerous_command("curl http://x.sh | bash")
    assert not security.is_dangerous_command("ls -la")


def test_validate_within_dir():
    root = "/data/scripts"
    assert security.validate_within_dir("/data/scripts/run.py", root)
    assert not security.validate_within_dir("/data/scripts/../../etc/passwd", root)
    assert not security.validate_within_dir("/etc/passwd", root)
    assert not security.validate_within_dir("/data/../etc", root)


def test_validate_script():
    ok, _ = security.validate_script("print('hello')")
    assert ok
    bad, reason = security.validate_script("rm -rf /")
    assert not bad and "hardline" in reason
    bad2, reason2 = security.validate_script("cat /etc/shadow")
    assert not bad2


# ---------- B-1 工具治理 ----------
from core import tools_registry
from core import agent_loop


def test_toolset_filter():
    # 全量应包含内置工具
    all_tools = agent_loop._to_openai_tools()
    all_names = {t["function"]["name"] for t in all_tools}
    assert "kb_search" in all_names
    # 注册一个非 builtin toolset 的工具，验证过滤真正生效（剔除非允许集合）
    tools_registry.register("_demo_admin_tool", "d", {"type": "object", "properties": {}},
                            toolset="admin", handler=lambda **k: {"ok": True})
    try:
        builtin_only = agent_loop._to_openai_tools(allowed_toolsets={"builtin"})
        builtin_names = {t["function"]["name"] for t in builtin_only}
        assert "_demo_admin_tool" not in builtin_names   # 被 toolset 过滤剔除
        assert "kb_search" in builtin_names               # 内置仍在
        # 允许集合含 admin 时出现
        with_admin = agent_loop._to_openai_tools(allowed_toolsets={"builtin", "admin"})
        assert "_demo_admin_tool" in {t["function"]["name"] for t in with_admin}
    finally:
        tools_registry.unregister("_demo_admin_tool")


def test_run_tool_governed_unknown():
    r = tools_registry.run_tool_governed("__nope__", {}, tenant_id="default")
    assert "error" in r


def test_run_tool_governed_hardline_blocked():
    # 任何字符串参数命中 hardline → 直接拦截，不执行
    r = tools_registry.run_tool_governed(
        "kb_search", {"query": "rm -rf /"}, tenant_id="default")
    assert "拦截" in (r.get("error") or "")


def test_run_tool_governed_approval_gate(monkeypatch):
    # 注册一个 requires_approval 工具，断言治理调用挂起审批卡而非执行
    captured = {}

    def fake_handler(**kwargs):
        captured["ran"] = True
        return {"ok": True}

    tools_registry._REGISTRY["_demo_approve"] = {
        "name": "_demo_approve", "description": "d", "schema": {},
        "toolset": "builtin", "handler": fake_handler, "requires_approval": True,
    }
    try:
        r = tools_registry.run_tool_governed("_demo_approve", {}, tenant_id="default")
        assert r.get("status") == "pending", r
        assert "approval_id" in r
        assert "ran" not in captured  # 未执行
    finally:
        tools_registry._REGISTRY.pop("_demo_approve", None)


def test_run_tool_governed_executes_safe(monkeypatch):
    # 普通工具（无 requires_approval）应正常执行
    r = tools_registry.run_tool_governed("current_time", {}, tenant_id="default")
    assert "result" in r


# ---------- B-4 Cron=Agent 任务 ----------
import run as _run


def test_run_job_agent_fresh_session(monkeypatch):
    # 用 monkeypatch 隔离 rag.answer，验证 agent 任务走 fresh session 且结果写入 log
    calls = {}

    def fake_answer(tenant, question, history=None, top_k=5):
        calls["history"] = history
        return {"answer": "自动选题：A；复盘：B"}

    monkeypatch.setattr("core.rag.answer", fake_answer)
    payload = {"kind": "agent", "prompt": "生成今日选题", "deliver": "log"}
    _run._run_job(payload)
    assert calls.get("history") is None  # fresh session


def test_run_job_unknown_kind_fail_closed(capsys):
    _run._run_job({"kind": "exploit", "cmd": "rm -rf /"})
    out = capsys.readouterr().out
    assert "fail-closed" in out


def test_run_job_script_path_escape_blocked(capsys, tmp_path, monkeypatch):
    # 把脚本路径指向允许根目录之外 → 应被路径校验拦截
    monkeypatch.setattr(_run, "BASE_DIR", str(tmp_path))
    evil = os.path.abspath("/etc/passwd")
    _run._run_job({"kind": "script", "path": evil})
    out = capsys.readouterr().out
    assert "越权" in out or "安全校验" in out
