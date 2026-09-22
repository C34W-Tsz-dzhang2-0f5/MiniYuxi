"""MiniYuxi CLI 回归测试（P2 CLI 落地验证）。

覆盖：
  - 参数解析与子命令完整性
  - version / doctor / ask / tools / skills 主路径
  - 延迟导入（--help 路径不得导入 core 内核，避免冷启动成本）
"""
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cli  # noqa: E402

EXPECTED_SUBCOMMANDS = {"chat", "ask", "doctor", "kb", "tools", "skills", "serve"}


def test_parser_exposes_all_subcommands():
    """三端 CLI 的 7 个子命令必须齐全。"""
    parser = cli.build_parser()
    actions = [a for a in parser._actions if a.dest == "cmd"]
    assert actions, "缺少 subparsers"
    choices = set(actions[0].choices.keys())
    assert EXPECTED_SUBCOMMANDS <= choices


def test_version_prints_version(capsys):
    assert cli.cmd_version(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "MiniYuxi CLI" in out


def test_help_path_does_not_import_kernel():
    """延迟导入：构建 parser / 打印 help 不应导入 core.rag（否则 --help 也要付冷启动）。"""
    code = (
        "import sys; sys.path.insert(0, r'%s');\n"
        "import cli; cli.build_parser();\n"
        "print('core.rag' in sys.modules)\n" % ROOT
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("False"), "help 路径不应导入 core.rag"


def test_doctor_builtin_runs():
    """基础体检应跑完且全部通过（LLM 凭证缺失仅 WARN，不计失败）。"""
    ok, total = cli._doctor_builtin()
    assert total >= 5
    assert ok == total, f"体检存在失败项：{ok}/{total}"


def test_ask_returns_answer(capsys):
    ns = argparse.Namespace(
        tenant="default", question="劳动合同", top_k=3,
        json=False, no_citations=True, max_citations=5,
    )
    assert cli.cmd_ask(ns) == 0
    out = capsys.readouterr().out.strip()
    assert out, "ask 应输出答案（离线兜底也应给出摘录）"


def test_tools_and_skills_non_empty(capsys):
    assert cli.cmd_tools(argparse.Namespace(json=False)) == 0
    assert "个工具" in capsys.readouterr().out

    assert cli.cmd_skills(argparse.Namespace(json=False)) == 0
    assert "个技能" in capsys.readouterr().out


def test_kb_search(capsys):
    ns = argparse.Namespace(tenant="default", query="劳动合同", top_k=3, json=False, kb_cmd="search")
    assert cli.cmd_kb(ns) == 0
    assert "命中" in capsys.readouterr().out


def test_unknown_input_does_not_crash():
    """未知/空输入应返回非 0 或正常处理，不抛裸异常。"""
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["not-a-command"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
