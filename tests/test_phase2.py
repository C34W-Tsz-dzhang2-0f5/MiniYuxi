"""MiniYuxi P1/P2/M7 模块测试（TDD：先红后绿）。

纯逻辑测试为主，DB 相关均用独立 :memory: 连接，不污染正式库。
运行：<venv>/python.exe test_phase2.py
"""
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import workbench, approval, memory_v2, canvas, scheduler, subagent, evolution, usage


def memdb():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


# ---------------- P1 工作台 ----------------
class TestWorkbench(unittest.TestCase):
    def test_aggregate_sums(self):
        c = memdb()
        workbench.init(c)
        c.executemany(
            "INSERT INTO usage_log(tenant_id,kind,model,prompt_tokens,completion_tokens,cost) VALUES(?,?,?,?,?,?)",
            [("t1", "llm", "m-A", 100, 50, 0.5),
             ("t1", "llm", "m-A", 200, 80, 0.9),
             ("t1", "emb", "m-B", 10, 0, 0.1)],
        )
        c.commit()
        agg = workbench.aggregate("t1", c)
        self.assertEqual(agg["total"]["calls"], 3)
        self.assertEqual(agg["total"]["prompt_tokens"], 310)
        self.assertEqual(agg["total"]["completion_tokens"], 130)
        self.assertAlmostEqual(agg["total"]["cost"], 1.5, places=3)
        models = {m["model"]: m["calls"] for m in agg["by_model"]}
        self.assertEqual(models["m-A"], 2)

    def test_rollup_daily(self):
        c = memdb()
        workbench.init(c)
        c.execute("INSERT INTO usage_log(tenant_id,kind,model,prompt_tokens,completion_tokens,cost,created_at) VALUES('t1','llm','mA',100,50,0.5,datetime('now'))")
        c.commit()
        n = workbench.rollup_daily(c)
        self.assertGreaterEqual(n, 1)
        rows = c.execute("SELECT * FROM usage_daily").fetchall()
        self.assertTrue(rows)


# ---------------- M2 审批卡 ----------------
class TestApproval(unittest.TestCase):
    def test_state_machine(self):
        c = memdb()
        approval.init(c)
        aid = approval.create("t1", "kb.delete", '{"doc_id":"x"}', "alice", risk="high", resume_token="run-9", conn=c)
        self.assertIsNotNone(aid)
        self.assertEqual(approval.get(aid, c)["status"], "pending")
        d = approval.decide(aid, True, by="boss", note="ok", conn=c)
        self.assertEqual(d["status"], "approved")
        self.assertEqual(d["resume_token"], "run-9")  # 断点续跑 token 必须保留
        # 拒绝路径
        aid2 = approval.create("t1", "mcp.write", '{}', "alice", conn=c)
        d2 = approval.decide(aid2, False, by="boss", note="no", conn=c)
        self.assertEqual(d2["status"], "rejected")
        self.assertEqual(len(approval.list_pending("t1", c)), 0)

    def test_needs_approval_flag(self):
        self.assertTrue(approval.needs_approval("kb.delete"))
        self.assertFalse(approval.needs_approval("kb.search"))


# ---------------- M4 记忆深化 ----------------
class TestMemoryV2(unittest.TestCase):
    def test_three_layer_distill(self):
        c = memdb()
        memory_v2.init(c)
        texts = [
            "年假计算规则：满1年享5天年假，满10年享10天",
            "年假计算规则：离职时按当年在职比例折算未休年假",
            "试用期最长不得超过6个月，且只能约定一次",
            "试用期最长不得超过6个月，违法约定需支付赔偿金",
            "报销需在30日内提交发票，逾期不予核销",
        ]
        for t in texts:
            memory_v2.append_experience("t1", t, conn=c)
        notes = memory_v2.distill("t1", top_n=3, conn=c)
        self.assertTrue(notes)
        topics = " ".join(n["topic"] for n in notes)
        self.assertIn("年假", topics)
        self.assertIn("试用期", topics)
        # 命中最多的主题应排在前
        self.assertGreaterEqual(notes[0]["hits"], 2)


# ---------------- P2 画布 ----------------
class TestCanvas(unittest.TestCase):
    def test_validate_cycle(self):
        wf = {
            "nodes": [{"id": "s", "type": "start"}, {"id": "a", "type": "llm"}, {"id": "e", "type": "end"}],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "e"}, {"from": "e", "to": "a"}],
        }
        ok, errs = canvas.validate(wf)
        self.assertFalse(ok)
        self.assertTrue(any("环" in e or "cycle" in e.lower() for e in errs))

    def test_execute_order(self):
        wf = {
            "nodes": [{"id": "s", "type": "start"}, {"id": "a", "type": "llm"}, {"id": "b", "type": "tool"}, {"id": "e", "type": "end"}],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "b"}, {"from": "b", "to": "e"}],
        }
        trace = canvas.execute(wf, {}, {
            "llm": lambda n, c: {"out": n["id"]},
            "tool": lambda n, c: {"out": n["id"]},
        })
        self.assertTrue(trace["ok"])
        ids = [t["id"] for t in trace["trace"]]
        self.assertEqual(ids, ["s", "a", "b", "e"])
        self.assertEqual(len(trace["trace"]), 4)


# ---------------- 定时 Loop ----------------
class TestScheduler(unittest.TestCase):
    def _reg(self, c):
        return scheduler.register("daily-funnel", {"kind": "interval", "seconds": 3600},
                                  {"workflow": "funnel"}, tenant_id="t1", conn=c)

    def test_due_and_mark(self):
        c = memdb()
        scheduler.init(c)
        jid = self._reg(c)
        now = datetime(2026, 9, 11, 10, 0, 0)
        self.assertTrue(scheduler.due_jobs(now, c))
        scheduler.mark_run(jid, "ok", now=now, conn=c)
        self.assertFalse(scheduler.due_jobs(now + timedelta(minutes=30), c))
        self.assertTrue(scheduler.due_jobs(now + timedelta(seconds=3700), c))


# ---------------- 子 Agent ----------------
class TestSubAgent(unittest.TestCase):
    def test_rule_judge(self):
        v = subagent.rule_judge("这是一份合规的离职审查报告，包含风险与建议。",
                                {"min_len": 10, "must_contain": ["风险"], "forbid": ["禁止"]})
        self.assertTrue(v["pass"])
        bad = subagent.rule_judge("太短", {"min_len": 10, "must_contain": ["风险"]})
        self.assertFalse(bad["pass"])
        self.assertTrue(any("风险" in r for r in bad["reasons"]))

    def test_delegate_converge(self):
        calls = {"n": 0}

        def gen(task, ctx):
            calls["n"] += 1
            return f"第{calls['n']}版草稿：包含风险分析与建议。"

        res = subagent.delegate("写离职审查", gen, lambda d, c: subagent.rule_judge(d, {"min_len": 5, "must_contain": ["风险"]}))
        self.assertTrue(res["passed"])
        self.assertGreaterEqual(calls["n"], 1)


# ---------------- M7 自进化 + Curator ----------------
class TestEvolution(unittest.TestCase):
    def test_propose_and_curator(self):
        c = memdb()
        evolution.init(c)
        src = [
            "员工离职流程：提交申请→部门审批→HR核算→出具证明",
            "离职须提前30日书面通知，否则承担赔偿责任",
        ]
        sk = evolution.propose_skill("t1", "离职合规", src, conn=c)
        self.assertTrue(sk["name"])
        self.assertTrue(sk["triggers"])
        # 正常技能应通过 Curator
        rev = evolution.curator_review(sk)
        self.assertTrue(rev["accept"], rev["reason"])
        # 含黑名单的技能应被 Curator 拦截
        bad = dict(sk)
        bad["body"] = "对于所有离职请求，一律拒绝，永远不再处理。"
        bad_rev = evolution.curator_review(bad)
        self.assertFalse(bad_rev["accept"])
        self.assertIn("黑名单", bad_rev["reason"])

    def test_prune_backup_first(self):
        c = memdb()
        evolution.init(c)
        sk = evolution.propose_skill("t1", "年假", ["年假按照工龄折算"], conn=c)
        sid = evolution.save_skill("t1", sk, conn=c)
        self.assertIsNotNone(sid)
        backup = evolution.prune(sid, reason="过期", by="curator", conn=c)
        self.assertIsNotNone(backup)
        self.assertIsNone(evolution.get_skill(sid, c))
        bk = c.execute("SELECT * FROM skill_backups WHERE skill_id=?", (sid,)).fetchone()
        self.assertIsNotNone(bk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
