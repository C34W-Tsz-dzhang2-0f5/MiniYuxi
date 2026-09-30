"""评估 Harness 离线测试（不依赖真实 LLM，验证指标计算 + 任务结构）。

历史问题：本文件原先是「import 期就打印 + sys.exit()」的脚本，
被 pytest 收集时触发 INTERNALERROR（collection 阶段退出，报告完全丢失）。
现改为标准 pytest 断言 + `__main__` 守卫，两种跑法都支持：

    pytest tests/test_eval.py -v
    python tests/test_eval.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, eval_harness  # noqa: E402

_TASKS = None
_REPORT = None


def _setup() -> None:
    """建库 + 构建示例任务 + 跑一次离线评估（模块级只做一次，pytest 与脚本共用）。"""
    global _TASKS, _REPORT
    if _TASKS is not None:
        return
    db.init_db()
    eval_harness.init()
    _TASKS = eval_harness.build_demo_tasks()
    h = eval_harness.EvalHarness("default")
    for t in _TASKS:
        h.add_task(t)
    _REPORT = h.run_all(k=1)


# --------------------------------------------------------------------------
# T1: 指标计算
# --------------------------------------------------------------------------

def test_pass_at_1():
    _setup()
    r1 = [{"passed": True}, {"passed": False}, {"passed": True}]
    assert eval_harness.pass_at_1(r1) == 2 / 3


def test_pass_at_k_prefix_mode():
    _setup()
    r1 = [{"passed": True}, {"passed": False}, {"passed": True}]
    assert eval_harness.pass_at_k(r1, k=1) == 2 / 3


def test_pass_at_k_any_attempt():
    _setup()
    r2 = [
        {"attempts": [{"passed": True}, {"passed": False}]},
        {"attempts": [{"passed": True}, {"passed": True}]},
    ]
    # 只要有一次通过即算通过
    assert eval_harness.pass_at_k(r2, k=2) == 1.0


def test_pass_consecutive_k():
    _setup()
    r2 = [
        {"attempts": [{"passed": True}, {"passed": False}]},
        {"attempts": [{"passed": True}, {"passed": True}]},
    ]
    # 全部通过才算通过
    assert eval_harness.pass_consecutive_k(r2, k=2) == 0.5


# --------------------------------------------------------------------------
# T2: 任务构建
# --------------------------------------------------------------------------

def test_build_demo_tasks_shape():
    _setup()
    assert len(_TASKS) == 5, f"5 个示例任务，实际={len(_TASKS)}"
    assert _TASKS[0].name == "基础回忆_公司年假规则"
    assert _TASKS[1].prefix_mode is False
    assert _TASKS[4].prefix_mode is True


# --------------------------------------------------------------------------
# T3: Harness 运行（离线）
# --------------------------------------------------------------------------

def test_report_shape():
    _setup()
    assert _REPORT["total_tasks"] == 5
    assert "pass_at_1" in _REPORT
    assert "details" in _REPORT


# --------------------------------------------------------------------------
# T4: 报告入库
# --------------------------------------------------------------------------

def test_report_persisted():
    _setup()
    eval_harness.save_report("test_run", _REPORT)
    conn = db.connect()
    row = conn.execute(
        "SELECT run_name, pass_at_1 FROM eval_reports "
        "WHERE run_name='test_run' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "报告未入库"
    assert row["run_name"] == "test_run"


# --------------------------------------------------------------------------
# 脚本入口
# --------------------------------------------------------------------------

def main() -> int:
    checks = [
        ("T1: 指标计算", [
            ("pass_at_1 = 2/3", lambda: eval_harness.pass_at_1(
                [{"passed": True}, {"passed": False}, {"passed": True}]) == 2 / 3),
            ("pass^k(k=2) = 0.5", lambda: eval_harness.pass_consecutive_k(
                [{"attempts": [{"passed": True}, {"passed": False}]},
                 {"attempts": [{"passed": True}, {"passed": True}]}], k=2) == 0.5),
        ]),
        ("T2: 任务构建", [
            ("5 个示例任务", lambda: len(_TASKS) == 5),
            ("任务 1 名称正确", lambda: _TASKS[0].name == "基础回忆_公司年假规则"),
            ("任务 5 前缀模式", lambda: _TASKS[4].prefix_mode is True),
        ]),
        ("T3: 报告结构", [
            ("总任务数=5", lambda: _REPORT["total_tasks"] == 5),
            ("报告含 pass_at_1", lambda: "pass_at_1" in _REPORT),
            ("报告含 details", lambda: "details" in _REPORT),
        ]),
        ("T4: 报告入库", [
            ("报告已入库", lambda: db.connect().execute(
                "SELECT 1 FROM eval_reports WHERE run_name='test_run' "
                "ORDER BY id DESC LIMIT 1").fetchone() is not None),
        ]),
    ]
    ok = True
    for title, items in checks:
        print(title)
        for name, fn in items:
            try:
                passed = bool(fn())
            except Exception as exc:                # noqa: BLE001
                passed, name = False, f"{name}（{type(exc).__name__}: {exc}）"
            ok &= passed
            print(f"  {'OK' if passed else 'FAIL'}: {name}")
    print("\n" + "=" * 40)
    print("ALL TESTS PASSED" if ok else "SOME TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    _setup()
    eval_harness.save_report("test_run", _REPORT)
    sys.exit(main())
