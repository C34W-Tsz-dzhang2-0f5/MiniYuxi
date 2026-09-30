# -*- coding: utf-8 -*-
"""2026-09-30 加固回归测试：agent_runtime / agent_loop 5 个高优先级缺口。

覆盖：
- T1 审批卡不再被当工具结果喂回模型（status=="pending" 分支）
- T2 协作式中断生效（cancel_check）
- T3 max_cost 闸门真的能触发（record_cost 已接线）
- T4 multitenant.enforce 已接入 agent_loop 入口
- T5 allowed_toolsets 按 toolset 过滤工具
- T6 取消后会话可再次 submit（cancelled 非死终态）

用 mock 打桩 gateway / tools_registry，不触网。
⚠️ 本文件匹配 .gitignore 的 test_*.py，入库需 git add -f。
"""
import os
import sys
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import agent_loop, agent_runtime, circuit_breaker  # noqa: E402


def _fake_tool_call(tid, name, args):
    return {"id": tid, "name": name, "arguments": args}


class TestToolsetFilter(unittest.TestCase):
    """T5：allowed_toolsets 按 toolset 过滤。"""

    def test_filter_by_toolset(self):
        with mock.patch("core.tools_registry.list_tools", return_value=[
            {"name": "hr_query", "description": "HR", "toolset": "hr", "schema": {}},
            {"name": "law_query", "description": "法务", "toolset": "law", "schema": {}},
        ]):
            allt = agent_loop._to_openai_tools()
            self.assertEqual(len(allt), 2, "None=全量暴露（向后兼容）")
            only_hr = agent_loop._to_openai_tools(["hr"])
            self.assertEqual(len(only_hr), 1)
            self.assertEqual(only_hr[0]["function"]["name"], "hr_query")
            self.assertEqual(agent_loop._to_openai_tools(["none"]), [], "空交集应为空列表")


class TestCostGate(unittest.TestCase):
    """T3：max_cost 闸门可达。"""

    def test_cost_gate_trips(self):
        g = circuit_breaker.BudgetGuard(tenant_id=None, max_cost=0.01, max_steps=999)
        self.assertEqual(g.check_step()[0], "closed", "初始应闭合")
        g.record_cost(0.5)
        decision, reason = g.check_step()
        self.assertEqual(decision, "open")
        self.assertEqual(reason, "max_cost", "record_cost 后 max_cost 闸门必须能触发")

    def test_estimate_cost_monotonic(self):
        a = agent_loop._estimate_cost(1000, 0, "deepseek-chat")
        b = agent_loop._estimate_cost(1000, 0, "gpt-4")
        self.assertGreater(b, a, "贵模型估算成本应更高")
        self.assertEqual(agent_loop._estimate_cost(0, 0, None), 0.0)
        # 坏输入不得抛异常
        self.assertEqual(agent_loop._estimate_cost(None, None, None), 0.0)


class TestPendingApproval(unittest.TestCase):
    """T1：审批卡挂起，不再当普通工具结果。"""

    def _run_with_pending(self):
        # 第一次 LLM 返回工具调用；治理层返回 pending；
        # 第二次 LLM（tools=[]）用于生成告知用户的最终答复。
        llm_responses = [
            {"ok": True, "text": "", "tool_calls": [_fake_tool_call("c1", "danger_tool", {})],
             "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            {"ok": True, "text": "该操作需先完成人工审批。", "tool_calls": [], "usage": None},
        ]
        pending = {"status": "pending", "approval_id": "AP-123", "tool_name": "danger_tool"}

        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.gateway.chat_with_tools", side_effect=llm_responses) as gw, \
             mock.patch("core.tools_registry.list_tools", return_value=[]), \
             mock.patch("core.tools_registry.run_tool_governed", return_value=pending):
            res = agent_loop.run("sys", "做危险操作", tenant_id="t1")
        return res, gw

    def test_pending_not_fed_back_as_result(self):
        res, gw = self._run_with_pending()
        self.assertIsNotNone(res, "不应因审批挂起而整体失败")
        # 关键断言：结果里带 pending_approval，且审批号没丢
        self.assertIn("pending_approval", res)
        self.assertEqual(res["pending_approval"]["approval_id"], "AP-123")
        self.assertEqual(res["pending_approval"]["tool"], "danger_tool")
        # 绝不能出现"工具已执行完"的语义
        self.assertNotIn("AP-123", str(res.get("answer") or "") or "")
        # 第二次 LLM 调用必须传空 tools（禁止挂起后继续调工具）
        self.assertEqual(gw.call_args_list[-1].args[2], [])

    def test_pending_trace_marked(self):
        res, _ = self._run_with_pending()
        trace = res.get("loop_trace") or []
        self.assertTrue(any(t.get("pending_approval") == "AP-123" for t in trace),
                        "loop_trace 应标记挂起而非执行结果")


class TestCancellation(unittest.TestCase):
    """T2/T6：协作式中断 + cancelled 非死终态。"""

    def test_cancel_check_breaks_loop(self):
        llm = {"ok": True, "text": "", "tool_calls": [_fake_tool_call("c1", "t", {})],
               "usage": None}
        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.gateway.chat_with_tools", return_value=llm), \
             mock.patch("core.tools_registry.list_tools", return_value=[]), \
             mock.patch("core.tools_registry.run_tool_governed",
                        return_value={"result": "ok"}):
            # 第一轮就要求取消 → 立即退出，不产生工具执行
            res = agent_loop.run("sys", "长任务", cancel_check=lambda: True)
        self.assertTrue(res.get("cancelled"), "cancel_check=True 应立即取消")
        self.assertEqual(res.get("tool_calls_used"), [])

    def test_cancel_false_runs_normally(self):
        llm = {"ok": True, "text": "完成", "tool_calls": [], "usage": None}
        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.gateway.chat_with_tools", return_value=llm), \
             mock.patch("core.tools_registry.list_tools", return_value=[]):
            res = agent_loop.run("sys", "问一句", cancel_check=lambda: False)
        self.assertFalse(res.get("cancelled"))
        self.assertEqual(res.get("answer"), "完成")

    def test_session_cancel_then_resubmit(self):
        """cancelled 不是死终态：取消后可再次 submit。"""
        s = agent_runtime.AgentSession("sid-1", "t1")
        self.assertTrue(s.is_cancelled() is False)
        s.cancel()
        self.assertTrue(s.is_cancelled(), "cancel() 后标志位应被 is_cancelled 读到")
        self.assertEqual(s.status, "cancelled")
        # 再次 submit 会重置标志
        with mock.patch.object(agent_runtime, "_executor") as ex:
            s.submit("再来一次")
            self.assertFalse(s.is_cancelled(), "submit 应重置取消标志")

    def test_session_passes_cancel_check_to_loop(self):
        """AgentSession._step 必须把 cancel_check 传给 agent_loop。"""
        s = agent_runtime.AgentSession("sid-2", "t1")
        with mock.patch("core.agent_loop.run", return_value={"answer": "x"}) as run:
            s._step("hello")
        kwargs = run.call_args.kwargs
        self.assertIn("cancel_check", kwargs, "必须传 cancel_check，否则取消永远不生效")
        # bound method 每次访问都是新对象，比较 __self__ 与 __func__
        cc = kwargs["cancel_check"]
        self.assertIs(cc.__self__, s)
        self.assertIs(cc.__func__, agent_runtime.AgentSession.is_cancelled)
        self.assertIn("allowed_toolsets", kwargs, "必须传 allowed_toolsets（最小权限）")


class TestMultitenantGate(unittest.TestCase):
    """T4：multitenant.enforce 已接入入口。"""

    def test_blocked_when_quota_exceeded(self):
        llm = {"ok": True, "text": "不该走到这", "tool_calls": [], "usage": None}
        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.multitenant.enforce",
                        return_value={"allow": False, "reason": "quota_daily_calls_exceeded"}), \
             mock.patch("core.gateway.chat_with_tools", return_value=llm) as gw:
            res = agent_loop.run("sys", "超额请求", tenant_id="t1")
        self.assertTrue(res.get("blocked"), "配额超额应被拦")
        self.assertEqual(res.get("block_reason"), "quota_daily_calls_exceeded")
        gw.assert_not_called()   # 被拦截时绝不能调用 LLM（零 token 消耗）

    def test_allowed_when_ok(self):
        llm = {"ok": True, "text": "正常答复", "tool_calls": [], "usage": None}
        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.multitenant.enforce", return_value={"allow": True, "reason": "ok"}), \
             mock.patch("core.gateway.chat_with_tools", return_value=llm):
            res = agent_loop.run("sys", "正常", tenant_id="t1")
        self.assertFalse(res.get("blocked"))
        self.assertEqual(res.get("answer"), "正常答复")

    def test_gate_failure_does_not_break_mainline(self):
        """闸门自身异常必须 fail-open，不得阻断主链路。"""
        llm = {"ok": True, "text": "兜底成功", "tool_calls": [], "usage": None}
        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.multitenant.enforce", side_effect=RuntimeError("db down")), \
             mock.patch("core.gateway.chat_with_tools", return_value=llm):
            res = agent_loop.run("sys", "正常", tenant_id="t1")
        self.assertIsNotNone(res, "闸门异常不得让整个 run 崩掉")
        self.assertEqual(res.get("answer"), "兜底成功")


if __name__ == "__main__":
    unittest.main(verbosity=2)
