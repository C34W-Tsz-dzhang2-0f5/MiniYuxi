"""深度构造 5 模块 TDD 测试（纯逻辑，:memory: 隔离；不依赖外部网络/Key）。"""
import sqlite3

TID = "ut_deep"


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def test_provider_router():
    from core import provider_router as pr
    c = _conn(); pr.init(c)
    pr.register_provider({"id": "sf", "name": "SiliconFlow", "kind": "openai",
                          "base_url": "https://x/v1", "api_key": "k", "model": "m1"}, c)
    pr.register_provider({"id": "of", "name": "Offline", "kind": "offline",
                          "base_url": "", "api_key": "", "model": "offline"}, c)
    assert len(pr.list_providers(c)) == 2
    # 热切换
    pr.set_active("sf", c)
    assert pr.get_active(c) == "sf"
    # 无 Key 供应商 → 离线兜底信封
    pr.register_provider({"id": "nokey", "name": "NoKey", "kind": "openai",
                          "base_url": "https://y/v1", "api_key": "", "model": "m2"}, c)
    pr.set_active("nokey", c)
    r = pr.chat("sys", "hi", conn=c)
    assert r["ok"] is False and r["provider"] == "offline", r
    # 注入式路由：显式 provider 命中
    pr.set_active("sf", c)
    calls = []
    def llm_fn(prov, payload):
        calls.append(prov["id"]); return f"echo:{prov['model']}", None
    r = pr.chat("sys", "hi", provider_id="sf", conn=c, llm_fn=llm_fn)
    assert r["ok"] and r["text"] == "echo:m1" and calls == ["sf"], r
    # 故障转移：主供应商报错 → 切到下一个带 Key 的 enabled 供应商
    pr.register_provider({"id": "backup", "name": "Backup", "kind": "openai",
                          "base_url": "https://b/v1", "api_key": "bk", "model": "m3"}, c)
    def llm_fn2(prov, payload):
        if prov["id"] == "sf":
            return None, "HTTP 500"
        return f"fallback:{prov['model']}", None
    r = pr.chat("sys", "hi", provider_id="sf", conn=c, llm_fn=llm_fn2)
    assert r["ok"] and "fallback" in r["text"], r
    print("  [ok] provider_router: 注册/热切换/离线兜底/显式路由/故障转移")


def test_connectors():
    from core import connectors as cn
    c = _conn(); cn.init(c)
    for k in ("wecom", "wechat", "crm", "erp", "feishu"):
        cid = cn.register(f"{k}-demo", k, conn=c)
        assert cid == f"{k}:{k}-demo"
    assert len(cn.list_connectors(c)) == 5
    h = cn.health(c)
    assert all(x["status"] == "not_configured" for x in h), h
    # 未配置 → not_configured 信封（不崩）
    r = cn.send_message("wecom:wecom-demo", "user1", "hello", conn=c)
    assert r["ok"] is False and r["status"] == "not_configured", r
    # 配置 endpoint+token 后 → ready，发送走 best-effort（无网络则 transport_error，仍不崩）
    cn.register("wecom-live", "wecom", {"endpoint": "http://127.0.0.1:9/hook", "token": "t"}, conn=c)
    st = {x["id"]: x["status"] for x in cn.health(c)}
    assert st["wecom:wecom-live"] == "ready", st
    print("  [ok] connectors: 5 类原生适配/健康探测/未配置降级")


def test_soc_audit():
    from core import soc_audit as sa
    c = _conn(); sa.init(c)
    for i in range(3):
        sa.log({"tenant_id": TID, "actor": "admin", "role": "admin", "action": f"act{i}",
                "target": "x", "result": "success", "severity": "info",
                "src_ip": "1.2.3.4", "detail": {"n": i}}, c)
    v = sa.verify_chain(c)
    assert v["ok"] and v["count"] == 3, v
    # 篡改检测：改一行 detail → 链断裂
    c.execute("UPDATE audit_events SET detail_json='{\"n\":999}' WHERE seq=2")
    v2 = sa.verify_chain(c)
    assert v2["ok"] is False and v2["broken_at"] == 2, v2
    # 查询/导出
    q = sa.query({"tenant_id": TID}, conn=c)
    assert len(q) == 3
    rep = sa.export(c)
    assert rep["chain"]["ok"] is False
    print("  [ok] soc_audit: 结构化事件/哈希链/篡改检测/查询导出")


def test_orchestration():
    from core import orchestration as oc, canvas
    c = _conn(); oc.init(c)
    # 多角色协同
    roles = [
        {"role": "planner", "system": "p", "criteria": {"min_len": 5}},
        {"role": "reviewer", "system": "r", "criteria": {"min_len": 5, "forbid": ["禁止词"]}},
    ]
    def llm_fn(sys, prompt):
        return "规划产出：完成任务步骤明确", None
    team = oc.run_team("写一个招聘流程", roles, conn=c, llm_fn=llm_fn)
    assert team["ok"] and len(team["contributions"]) == 2, team
    # 工作流自动化（canvas DAG）
    wf = {"name": "wf1", "nodes": [
        {"id": "s", "type": "start"},
        {"id": "a", "type": "llm", "next": ["e"]},
        {"id": "e", "type": "end"},
    ]}
    handlers = {t: (lambda ctx, n, t=t: f"done:{t}") for t in ("llm", "tool", "knowledge", "approval", "subagent")}
    out = oc.run_automation(wf, "manual", {}, handlers, conn=c)
    assert out["ok"] and any(n["id"] == "a" for n in out["trace"]), out
    print("  [ok] orchestration: 多 Agent 协同闭环/工作流自动化")


def test_multitenant():
    from core import multitenant as mt
    c = _conn(); mt.init(c)
    mt.set_policy(TID, {"mlps_level": "L3", "quota_daily_calls": 10, "cmk_enabled": True,
                        "cmk_key_id": "kms://key1"}, c)
    p = mt.get_policy(TID, c)
    assert p["mlps_level"] == "L3" and p["cmk_enabled"] == 1
    # 配额闸门
    assert mt.enforce(TID, "chat", {"daily_calls": 9}, c)["allow"] is True
    assert mt.enforce(TID, "chat", {"daily_calls": 10}, c)["allow"] is False
    # readiness 账本：区分 code_done / external_required
    rd = mt.readiness(c)
    assert "code_done" in rd["mlps_level3"] and "external_required" in rd["mlps_level3"]
    assert "external_required" in rd["saas_ha"]
    print("  [ok] multitenant: 租户策略/配额闸门/合规就绪度账本")


if __name__ == "__main__":
    test_provider_router()
    test_connectors()
    test_soc_audit()
    test_orchestration()
    test_multitenant()
    print("ALL_DEEP_OK")
