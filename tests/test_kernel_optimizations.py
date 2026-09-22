"""内核性能与安全优化回归测试（O6 冷启动懒加载 / O7 工具审计 / O8 联网审批开关）。

O6：sqlite_vec 不再顶层 import —— `import core.db` 不得拖入 numpy；向量功能仍需可用。
O7：run_tool_governed 每个出口都要落审计（success / rejected / blocked）。
O8：web_search 审批门默认关闭（保持自动化流畅），可由环境变量开启。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import db, soc_audit, tools_registry  # noqa: E402

# ───────────────────────── O6 冷启动懒加载 ─────────────────────────


def test_db_import_does_not_load_numpy():
    """`import core.db` 不应连带加载 numpy（否则 CLI/冷启动白付 ~350ms）。"""
    code = (
        "import sys; sys.path.insert(0, r'%s');\n"
        "import core.db;\n"
        "print('numpy' in sys.modules, 'sqlite_vec' in sys.modules)\n" % ROOT
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False False", f"期望 numpy/sqlite_vec 均未加载，实际 {r.stdout!r}"


def test_vec_extension_still_available_after_connect():
    """懒加载不能牺牲功能：建连后 sqlite-vec 必须可用。"""
    assert db.vec_version().startswith("v"), f"向量扩展不可用：{db.vec_version()}"


def test_db_connect_pragmas_intact():
    """O1 的并发韧性 pragma 不能被 O6 改动破坏。"""
    c = db.connect()
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# ───────────────────────── O7 工具调用审计 ─────────────────────────


def _audit_count() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]


def _last_audit():
    return db.connect().execute(
        "SELECT target, result, severity FROM audit_events ORDER BY id DESC LIMIT 1"
    ).fetchone()


def test_tool_call_writes_audit():
    soc_audit.init()
    before = _audit_count()
    tools_registry.run_tool_governed("calc", {"expression": "2+2"}, tenant_id="default")
    assert _audit_count() == before + 1, "正常执行应留一条审计"
    row = _last_audit()
    assert row["target"] == "calc" and row["result"] == "success"


def test_unknown_tool_audited_as_rejected():
    soc_audit.init()
    before = _audit_count()
    tools_registry.run_tool_governed("no_such_tool", {}, tenant_id="default")
    assert _audit_count() == before + 1
    row = _last_audit()
    assert row["result"] == "rejected" and row["severity"] == "warn"


def test_hardline_block_audited_as_critical():
    soc_audit.init()
    before = _audit_count()
    res = tools_registry.run_tool_governed("calc", {"expression": "rm -rf /"}, tenant_id="default")
    assert "error" in res, "hardline 命令必须被拦截"
    assert _audit_count() == before + 1
    row = _last_audit()
    assert row["result"] == "blocked" and row["severity"] == "critical"


# ───────────────────────── O8 联网审批开关 ─────────────────────────


def test_web_search_approval_default_off():
    """默认关闭 —— 不破坏既有自动化流程。"""
    assert tools_registry._REGISTRY["web_search"]["requires_approval"] is False


def test_web_search_approval_switchable_by_env():
    """环境变量开启后，web_search 应挂起审批而非直接执行。"""
    code = (
        "import os, sys; os.environ['MINIYUXI_APPROVE_WEB_SEARCH']='1';\n"
        "sys.path.insert(0, r'%s');\n"
        "from core import tools_registry as tr;\n"
        "r = tr.run_tool_governed('web_search', {'query':'ping'}, tenant_id='default');\n"
        "print(r.get('status'))\n" % ROOT
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "pending", f"开启后应挂起审批，实际 {r.stdout!r}"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
