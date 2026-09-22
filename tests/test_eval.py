"""评估 Harness 离线测试（不依赖真实 LLM，验证指标计算 + 任务结构）。"""
import sys
sys.path.insert(0, '.')

from core import eval_harness, db

db.init_db()
eval_harness.init()


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return False
    print(f"  OK: {msg}")
    return True


ok = True

# T1: 指标计算
print("T1: 指标计算")
r1 = [{"passed": True}, {"passed": False}, {"passed": True}]
ok &= check(eval_harness.pass_at_1(r1) == 2/3, "pass_at_1 = 2/3")
ok &= check(eval_harness.pass_at_k(r1, k=1) == 2/3, "pass_at_k(k=1) = 2/3")
r2 = [{"attempts": [{"passed": True}, {"passed": False}]}, {"attempts": [{"passed": True}, {"passed": True}]}]
ok &= check(eval_harness.pass_at_k(r2, k=2) == 1.0, "pass_at_k(k=2) = 1.0 (至少一次通过)")
ok &= check(eval_harness.pass_consecutive_k(r2, k=2) == 0.5, "pass^k(k=2) = 0.5 (两次都通过)")

# T2: 任务构建
print("T2: 任务构建")
tasks = eval_harness.build_demo_tasks()
ok &= check(len(tasks) == 5, f"5 个示例任务，实际={len(tasks)}")
ok &= check(tasks[0].name == "基础回忆_公司年假规则", "任务 1 名称正确")
ok &= check(tasks[1].prefix_mode == False, "任务 2 非前缀模式")
ok &= check(tasks[4].prefix_mode == True, "任务 5 前缀模式")

# T3: Harness 运行（离线，不依赖 LLM）
print("T3: Harness 运行（离线）")
h = eval_harness.EvalHarness("default")
for t in tasks:
    h.add_task(t)
report = h.run_all(k=1)
ok &= check(report["total_tasks"] == 5, f"总任务数=5，实际={report['total_tasks']}")
ok &= check("pass_at_1" in report, "报告含 pass_at_1")
ok &= check("details" in report, "报告含 details")

# T4: 报告保存
print("T4: 报告保存")
eval_harness.save_report("test_run", report)
conn = db.connect()
row = conn.execute("SELECT run_name, pass_at_1 FROM eval_reports WHERE run_name='test_run' ORDER BY id DESC LIMIT 1").fetchone()
ok &= check(row is not None, "报告已入库")
ok &= check(row["run_name"] == "test_run", "run_name 正确")

print("\n" + "="*40)
if ok:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
sys.exit(0 if ok else 1)
