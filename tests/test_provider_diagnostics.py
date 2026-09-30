"""供应商配置自由化 + 降级诊断（2026-09-30 线上排障后补）。

背景：用户报「start_miniyuxi.bat 启动后无法登录」。实际排查发现登录接口一直正常，
真因是 SiliconFlow Key 已失效（HTTP 401），问答静默降级成本地摘录，
用户看到的只是「答不出来」，无从判断是自己没上传文档还是 Key 挂了。

本文件锁三件事：
  1. rag.answer 在 Agent 全供应商失败时，必须透出 mode=degraded + 精确 reason；
  2. provider_router.probe 必须能区分 401/402/403/404/429 这类错误（给界面可读提示）；
  3. /api/gateway/providers 不得回吐明文 api_key（安全底线）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------- 1. 降级诊断

def _stub_offline(monkeypatch):
    """把 agent_loop 的 LLM 出口打成「全供应商失败」。"""
    from core import agent_loop, rag

    def _fail(system, messages, tools=None, tenant_id=None, provider=None, model=None):
        return {"ok": False, "text": "", "tool_calls": [],
                "err": "all_providers_failed", "model": "offline",
                "provider": "offline", "usage": None, "cost": None,
                "attempts": [{"provider": "siliconflow", "model": "m",
                              "ok": False, "err": "HTTP 401"}]}
    monkeypatch.setattr(agent_loop, "_llm_chat", _fail)
    monkeypatch.setattr(rag.config, "llm_enabled", lambda: True)
    # search() 的返回必须带 doc_id/score —— rag.answer 会据此拼 citations
    monkeypatch.setattr(rag, "search", lambda *a, **k: [
        {"doc_id": 1, "title": "员工手册", "score": 0.9,
         "text": "职工工作满1年不满10年的，可享受5天带薪年休假。"}])
    monkeypatch.setattr(rag, "_rag_single", lambda *a, **k: {
        "answer": "（本地摘录）", "citations": [], "mode": "offline"})
    return rag


def test_degraded_exposes_reason_not_silent(monkeypatch):
    """🔴 核心回归：Key 失效时不能静默降级，必须能被上层看到真因。"""
    rag = _stub_offline(monkeypatch)
    out = rag.answer("default", "带薪年休假怎么算")
    assert out["mode"] == "degraded", "全供应商失败时 mode 必须是 degraded，而非 offline"
    assert out["reason"] == "all_providers_failed"
    assert out["llm_attempts"][0]["err"] == "HTTP 401", "必须保留供应商级具体状态码"


def test_degraded_warning_names_401_cause(monkeypatch):
    """提示文案必须点名 401，否则用户仍会去怀疑「是不是没上传文档」。"""
    rag = _stub_offline(monkeypatch)
    out = rag.answer("default", "带薪年休假怎么算")
    warns = " ".join(out.get("warnings") or [])
    assert "401" in warns
    assert "Key" in warns


def test_last_error_reset_between_runs(monkeypatch):
    """失败现场不能跨请求残留：上一次 401 不该让下一次成功也带 degraded 标记。"""
    from core import agent_loop
    rag = _stub_offline(monkeypatch)
    rag.answer("default", "问题一")
    assert agent_loop.last_error()["err"] == "all_providers_failed"
    agent_loop.reset_last_error()
    assert agent_loop.last_error()["err"] == ""


def test_degrade_hint_covers_common_codes():
    """401/402/403/404/429 是最常见的五种，映射表必须都覆盖到。"""
    from core.rag import _DEGRADE_HINT
    for code in ("HTTP 401", "HTTP 402", "HTTP 403", "HTTP 404", "HTTP 429"):
        assert code in _DEGRADE_HINT, f"{code} 缺少运维可读提示"
        assert len(_DEGRADE_HINT[code]) > 8, f"{code} 的提示过于简略"


# ---------------------------------------------------------------- 2. probe 验活

def test_probe_reports_401_with_hint(monkeypatch):
    from core import provider_router

    class R:
        status_code = 401
        text = '{"code":30014,"message":"Token is invalid."}'

    monkeypatch.setattr(provider_router.requests, "post", lambda *a, **k: R())
    r = provider_router.probe({"base_url": "https://x/v1", "api_key": "k", "model": "m"})
    assert r["ok"] is False
    assert r["err"] == "HTTP 401"
    assert "Key" in r["hint"], "401 的提示必须指向 Key 本身"
    assert "Token is invalid" in r["detail"], "原始报文要能回传给界面做 title 提示"


def test_probe_distinguishes_404_and_429(monkeypatch):
    """404（模型名错）与 429（限流）必须给不同提示，否则用户无法对症。"""
    from core import provider_router

    def mk(code):
        class R:
            status_code = code
            text = "{}"
        return R()

    monkeypatch.setattr(provider_router.requests, "post", lambda *a, **k: mk(404))
    r404 = provider_router.probe({"base_url": "u", "api_key": "k", "model": "m"})
    monkeypatch.setattr(provider_router.requests, "post", lambda *a, **k: mk(429))
    r429 = provider_router.probe({"base_url": "u", "api_key": "k", "model": "m"})
    assert r404["hint"] != r429["hint"]
    assert "模型名" in r404["hint"]


def test_probe_ok_does_not_raise(monkeypatch):
    from core import provider_router

    class R:
        status_code = 200
        text = "{}"

    monkeypatch.setattr(provider_router.requests, "post", lambda *a, **k: R())
    r = provider_router.probe({"base_url": "u", "api_key": "k", "model": "m"})
    assert r["ok"] is True


def test_probe_handles_network_error(monkeypatch):
    """探测失败是正常结果，绝不能抛异常打断请求。"""
    from core import provider_router

    def _boom(*a, **k):
        raise provider_router.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(provider_router.requests, "post", _boom)
    r = provider_router.probe({"base_url": "u", "api_key": "k", "model": "m"})
    assert r["ok"] is False and r["err"] == "network"


# ---------------------------------------------------------------- 3. Key 不外泄

def test_providers_endpoint_masks_api_key():
    """🔴 安全底线：GET /api/gateway/providers 绝不能回吐明文 Key。"""
    import inspect

    import api
    src = inspect.getsource(api.gw_providers)
    assert "has_key" in src, "必须用 has_key 代替明文"
    assert "if k != \"api_key\"" in src or "if k != 'api_key'" in src, \
        "必须显式从返回体里剔除 api_key 字段"


def test_register_provider_roundtrip_stores_key():
    """注册后应能读回（供路由使用），这是配置生效的前提。"""
    from core import db, provider_router
    provider_router.init()
    provider_router.register_provider({
        "id": "unit-test-p", "name": "UT", "kind": "openai",
        "base_url": "https://example.invalid/v1", "api_key": "sk-unit",
        "model": "m", "priority": 0, "enabled": True,
    }, db.connect())
    rows = [p for p in provider_router.list_providers() if p["id"] == "unit-test-p"]
    assert rows and rows[0]["api_key"] == "sk-unit"
    provider_router.remove_provider("unit-test-p", db.connect())
    assert not [p for p in provider_router.list_providers() if p["id"] == "unit-test-p"]


# ---------------------------------------------------------------- 4. health 探活

def test_health_reports_degraded_when_key_invalid(monkeypatch):
    """配了 Key 但用不了时，health 必须报 degraded —— 这是本次排障最大的弯路来源。"""
    import api
    from core import config

    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(api.provider_router, "chat",
                        lambda *a, **k: {"ok": False, "err": "HTTP 401"})
    d = api.health()
    assert d["modes"]["llm"] == "degraded"
    assert d["llm_probe"] == "HTTP 401"


def test_health_offline_when_no_key(monkeypatch):
    import api
    from core import config
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    d = api.health()
    assert d["modes"]["llm"] == "offline-fallback"
    assert d["llm_probe"] is None, "没配 Key 时不该白跑一次探活"
