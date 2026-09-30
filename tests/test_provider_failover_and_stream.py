"""2026-09-30 回归：provider_router 故障转移 + MAX_LOOPS 配置化 + /api/chat 真流式。

对应本轮三项改造：
  A. agent_loop 改走 provider_router，主供应商 429/5xx/超时后自动切下一个；
  B. MAX_LOOPS 由 core/config.py 统一管理，且与 BudgetGuard.max_steps 保持一致；
  C. /api/chat?stream=true 消费 agent_loop 的 _emit 真实事件，不再是伪流式切片。
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, provider_router  # noqa: E402


def _register(conn, pid, model, key="k-" + "x"):
    conn.execute(
        "INSERT OR REPLACE INTO llm_providers(id,name,kind,base_url,api_key,model,priority,enabled) "
        "VALUES(?,?,?,?,?,?,?,1)",
        (pid, pid, "openai", "https://example.invalid/%s" % pid, key, model, 0),
    )
    conn.commit()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _ok_resp(text="", tool_calls=None, usage=None):
    msg = {"content": text, "tool_calls": tool_calls or []}
    return _Resp({"choices": [{"message": msg}], "usage": usage or {}})


class TestProviderFailover(unittest.TestCase):
    """A：chat_with_tools 的多供应商故障转移。"""

    def setUp(self):
        from core import db
        provider_router.init()          # 建 llm_providers / kv_store 表
        self.conn = db.connect()
        self.conn = db.connect()
        # 清空注册表，保证每个用例从「空表」起算（不污染真实 data/miniyuxi.db 的
        # 业务数据：这里只删 provider 行，且用例内自行注册需要的行）。
        self.conn.execute("DELETE FROM llm_providers")
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM llm_providers")
            self.conn.execute("DELETE FROM kv_store WHERE key='active_provider'")
            self.conn.commit()
        except Exception:
            pass

    def test_failover_to_second_provider(self):
        _register(self.conn, "p1", "m1")
        _register(self.conn, "p2", "m2")
        calls = []

        def fake_post(payload, prov, tenant_id=None):
            calls.append(prov["id"])
            if prov["id"] == "p1":
                return None, "HTTP 429"
            return _ok_resp(text="来自 p2 的答复"), None

        with mock.patch.object(provider_router, "_post", side_effect=fake_post):
            r = provider_router.chat_with_tools("sys", [{"role": "user", "content": "hi"}],
                                                tools=[], provider_id="p1", conn=self.conn)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["provider"], "p2", "应故障转移到第二个供应商")
        self.assertEqual(calls, ["p1", "p2"], "主供应商失败后才尝试下一个")

    def test_failover_uses_own_model(self):
        """🔴 回归：故障转移后不能继续用主供应商的模型名（部分网关直接 400）。"""
        _register(self.conn, "p1", "m1")
        _register(self.conn, "p2", "m2")
        seen = []

        def fake_post(payload, prov, tenant_id=None):
            seen.append((prov["id"], payload.get("model")))
            if prov["id"] == "p1":
                return None, "timeout"
            return _ok_resp(text="ok"), None

        with mock.patch.object(provider_router, "_post", side_effect=fake_post):
            provider_router.chat_with_tools("sys", [{"role": "user", "content": "hi"}],
                                            tools=[], provider_id="p1", conn=self.conn)
        self.assertEqual(seen, [("p1", "m1"), ("p2", "m2")],
                         "每个供应商应使用各自的 model")

    def test_tool_calls_parsed(self):
        _register(self.conn, "p1", "m1")
        raw = [{"id": "tc1", "type": "function",
                "function": {"name": "current_time", "arguments": '{"tz":"UTC"}'}}]
        with mock.patch.object(provider_router, "_post",
                               return_value=(_ok_resp(tool_calls=raw), None)):
            r = provider_router.chat_with_tools("sys", [{"role": "user", "content": "几点"}],
                                                tools=[{"type": "function"}],
                                                provider_id="p1", conn=self.conn)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["tool_calls"]), 1)
        self.assertEqual(r["tool_calls"][0]["name"], "current_time")
        self.assertEqual(r["tool_calls"][0]["arguments"], {"tz": "UTC"})

    def test_bad_arguments_degrade_to_empty(self):
        _register(self.conn, "p1", "m1")
        raw = [{"id": "tc1", "function": {"name": "x", "arguments": "{不是 json"}}]
        with mock.patch.object(provider_router, "_post",
                               return_value=(_ok_resp(tool_calls=raw), None)):
            r = provider_router.chat_with_tools("sys", [{"role": "user", "content": "x"}],
                                                tools=[], provider_id="p1", conn=self.conn)
        self.assertEqual(r["tool_calls"][0]["arguments"], {},
                         "参数非法时应降级为空 dict，不得抛异常")

    def test_all_failed_returns_offline_envelope(self):
        _register(self.conn, "p1", "m1")
        with mock.patch.object(provider_router, "_post", return_value=(None, "HTTP 500")):
            r = provider_router.chat_with_tools("sys", [{"role": "user", "content": "x"}],
                                                tools=[], provider_id="p1", conn=self.conn)
        self.assertFalse(r["ok"])
        self.assertEqual(r["err"], "all_providers_failed")
        self.assertEqual(r["provider"], "offline")
        self.assertTrue(r["attempts"], "应保留每个供应商的失败原因供排障")

    def test_empty_registry_falls_back_to_config(self):
        """🔴 回归：注册表为空时须回落 config.LLM_PROVIDERS，否则未注册过的部署
        会集体退化成 offline（表现为「配了 Key 却说离线」）。"""
        from core import config as cfg
        fake = [{"id": "siliconflow", "name": "SF", "kind": "openai",
                 "base_url": "https://api.siliconflow.cn/v1", "api_key": "sk-test",
                 "model": "Qwen/Qwen2.5-72B-Instruct", "priority": 0, "enabled": True}]
        with mock.patch.object(cfg, "LLM_PROVIDERS", fake), \
             mock.patch.object(provider_router, "_post",
                               return_value=(_ok_resp(text="ok"), None)):
            prov, order = provider_router._order_for(None, self.conn)
        self.assertIsNotNone(prov)
        self.assertEqual(prov["id"], "siliconflow")

    def test_offline_provider_short_circuits(self):
        r = provider_router.chat_with_tools("sys", [], tools=[], provider_id="offline",
                                            conn=self.conn)
        self.assertFalse(r["ok"])
        self.assertEqual(r["err"], "offline")
        self.assertEqual(r["tool_calls"], [])


class TestAgentLoopUsesRouter(unittest.TestCase):
    """A：agent_loop 的 LLM 出口确实是 provider_router。"""

    def test_llm_chat_delegates_to_router(self):
        from core import agent_loop
        sentinel = {"ok": True, "text": "x", "tool_calls": [], "err": "",
                    "usage": None, "attempts": []}
        with mock.patch("core.provider_router.chat_with_tools", return_value=sentinel) as m:
            got = agent_loop._llm_chat("sys", [], [], tenant_id="t1", provider="p1", model="m1")
        self.assertEqual(got, sentinel)
        self.assertEqual(m.call_args.kwargs["provider_id"], "p1")
        self.assertEqual(m.call_args.kwargs["model"], "m1")

    def test_failover_event_emitted(self):
        """切换供应商时应 emit lifecycle:failover，便于排障与对账。"""
        from core import agent_loop
        responses = [
            {"ok": True, "text": "答", "tool_calls": [], "usage": None,
             "provider": "p2", "attempts": [{"provider": "p1", "ok": False, "err": "HTTP 429"},
                                            {"provider": "p2", "ok": True, "err": ""}]},
        ]
        events = []
        with mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.provider_router.chat_with_tools", side_effect=responses), \
             mock.patch("core.tools_registry.list_tools", return_value=[]):
            agent_loop.run("sys", "问题", emit=events.append)
        phases = [e["payload"].get("phase") for e in events if e["type"] == "lifecycle"]
        self.assertIn("failover", phases, "应上报 failover 事件，实际 phases=%s" % phases)


class TestMaxLoopsConfig(unittest.TestCase):
    """B：MAX_LOOPS 来自 config，且与熔断步数阈值自洽。"""

    def test_max_loops_from_config(self):
        from core import agent_loop
        self.assertEqual(agent_loop.MAX_LOOPS, int(config.AGENT_MAX_LOOPS))

    def test_max_steps_exceeds_max_loops(self):
        self.assertGreater(config.RUN_MAX_STEPS, config.AGENT_MAX_LOOPS,
                           "步数闸门必须晚于轮数上限触发，否则轮数配置形同虚设")

    def test_env_override(self):
        import importlib
        old = os.environ.get("MINIYUXI_AGENT_MAX_LOOPS")
        os.environ["MINIYUXI_AGENT_MAX_LOOPS"] = "11"
        try:
            c2 = importlib.reload(config)
            self.assertEqual(c2.AGENT_MAX_LOOPS, 11)
            self.assertGreater(c2.RUN_MAX_STEPS, 11)
        finally:
            if old is None:
                os.environ.pop("MINIYUXI_AGENT_MAX_LOOPS", None)
            else:
                os.environ["MINIYUXI_AGENT_MAX_LOOPS"] = old
            importlib.reload(config)

    def test_loop_respects_configured_limit(self):
        """轮数上限真的被使用：把 MAX_LOOPS 压到 2，循环最多跑 2 轮。"""
        from core import agent_loop
        llm = {"ok": True, "text": "", "tool_calls": [
            {"id": "c", "name": "t", "arguments": {}}], "usage": None}
        with mock.patch.object(agent_loop, "MAX_LOOPS", 2), \
             mock.patch("core.config.llm_enabled", return_value=True), \
             mock.patch("core.provider_router.chat_with_tools", return_value=llm) as m, \
             mock.patch("core.tools_registry.list_tools", return_value=[]), \
             mock.patch("core.tools_registry.run_tool_governed", return_value={"result": "ok"}):
            res = agent_loop.run("sys", "任务")
        self.assertEqual(m.call_count, 2, "实际 LLM 调用次数应等于 MAX_LOOPS")


class TestChatSseRealStream(unittest.TestCase):
    """C：/api/chat?stream=true 消费 _emit 真实事件。"""

    def setUp(self):
        from fastapi.testclient import TestClient
        import api as api_mod
        from core import auth as core_auth
        self.client = TestClient(api_mod.app)
        # 走真实鉴权链（admin token），只桩掉 LLM/检索内核 —— 比桩 need() 更能
        # 保证「路由真的注册了、依赖真的解析了」。
        self.headers = {"Authorization": "Bearer " + core_auth.make_token(
            {"tid": "default", "sub": "sse-test", "role": "admin"})}

    def _stream(self, fake_answer):
        import api as api_mod
        with mock.patch.object(api_mod.rag, "answer", side_effect=fake_answer) as ra:
            r = self.client.post("/api/chat?stream=true", headers=self.headers,
                                 json={"question": "hi"})
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertIn("text/event-stream", r.headers.get("content-type", ""))
        return ra, r.text

    def test_sse_consumes_emit_events(self):
        events = [
            {"type": "lifecycle", "payload": {"phase": "start"}},
            {"type": "tool", "payload": {"event": "call", "tool": "current_time"}},
            {"type": "tool", "payload": {"event": "result", "tool": "current_time", "result": "12:00"}},
            {"type": "assistant", "payload": {"delta": "现在 12:00"}},
            {"type": "lifecycle", "payload": {"phase": "end"}},
        ]

        def fake_answer(tenant_id, question, top_k=5, history=None, emit=None):
            for e in events:
                emit(e)
            return {"answer": "现在 12:00", "citations": [], "mode": "agent"}

        ra, text = self._stream(fake_answer)
        # 旧契约：message/meta/done 仍在
        self.assertIn("event: message", text)
        self.assertIn("event: meta", text)
        self.assertIn("event: done", text)
        # 新契约：过程事件直达
        self.assertIn("event: tool", text)
        self.assertIn("event: assistant", text)
        self.assertIn("现在 12:00", text)
        self.assertTrue(ra.called, "rag.answer 必须收到 emit 回调")

    def test_no_fake_slicing(self):
        """🔴 回归：不得再出现 12 字符切片 + sleep 的伪流式。
        判据：单帧 delta 应为完整答案，而非 12 字碎片。"""
        def fake_answer(tenant_id, question, top_k=5, history=None, emit=None):
            if emit:
                emit({"type": "assistant", "payload": {"delta": "A" * 200}})
            return {"answer": "A" * 200, "citations": [], "mode": "agent"}

        _, text = self._stream(fake_answer)
        deltas = []
        for block in text.split("\n\n"):
            for line in block.splitlines():
                if line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if isinstance(d, dict) and d.get("delta"):
                        deltas.append(d["delta"])
        self.assertTrue(deltas)
        self.assertTrue(any(len(d) > 12 for d in deltas),
                        "delta 应为完整增量（真实事件），而非 12 字符切片：%r" % deltas[:3])

    def test_done_is_last_frame(self):
        def fake_answer(tenant_id, question, top_k=5, history=None, emit=None):
            return {"answer": "x", "citations": [], "mode": "offline"}

        _, text = self._stream(fake_answer)
        self.assertTrue(text.rstrip().endswith("data: {}"), "最后一帧必须是 event: done")

    def test_exception_becomes_lifecycle_error(self):
        def boom(tenant_id, question, top_k=5, history=None, emit=None):
            raise RuntimeError("内核炸了")

        _, text = self._stream(boom)
        self.assertIn("event: lifecycle", text)
        self.assertIn("内核炸了", text)
        self.assertIn("event: done", text, "异常后仍须收尾，前端不能挂住")


if __name__ == "__main__":
    unittest.main(verbosity=2)
